use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use quinn::{ClientConfig, Endpoint, ServerConfig};
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use rustls::{RootCertStore, ServerConfig as RustlsServerConfig};
use rustls_pemfile::{certs, private_key};

use std::fs::File;
use std::io::BufReader;
use std::{
    error::Error,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    sync::Arc,
};

fn load_certs(path: &Path) -> Vec<CertificateDer<'static>> {
    let mut reader = BufReader::new(File::open(path).unwrap());
    certs(&mut reader).map(|c| c.unwrap()).collect()
}

fn load_key(path: &Path) -> PrivateKeyDer<'static> {
    let mut reader = BufReader::new(File::open(path).unwrap());
    private_key(&mut reader).unwrap().unwrap()
}

fn make_server_config() -> anyhow::Result<(ServerConfig, CertificateDer<'static>)> {
    let certs_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let cert_path = certs_dir.join("server.crt");
    let key_path = certs_dir.join("server.key");

    let cert_chain = load_certs(&cert_path);
    let server_cert = cert_chain
        .first()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("no certificates loaded"))?;
    let key = load_key(&key_path);

    let mut rustls_config = RustlsServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(cert_chain, key)
        .unwrap();
    rustls_config.alpn_protocols = vec![b"h3".to_vec()];

    let quic_crypto = QuicServerConfig::try_from(rustls_config).unwrap();
    let server_config = ServerConfig::with_crypto(Arc::new(quic_crypto));
    //let transport_config = Arc::get_mut(&mut server_config.transport).unwrap();
    //transport_config.max_concurrent_uni_streams(0_u8.into());
    Ok((server_config, server_cert))
}

fn make_client_config(cert_path: &Path) -> ClientConfig {
    let certs = load_certs(cert_path);

    let mut roots = RootCertStore::empty();
    for cert in certs {
        roots.add(cert).unwrap();
    }

    let mut rustls = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();

    rustls.alpn_protocols = vec![b"h3".to_vec()];
    let quic_crypto = QuicClientConfig::try_from(rustls).unwrap();

    ClientConfig::new(Arc::new(quic_crypto))
}

#[allow(unused)]
pub fn make_client_endpoint(
    bind_addr: SocketAddr,
) -> Result<Endpoint, Box<dyn Error + Send + Sync + 'static>> {
    //let client_cfg = configure_client(server_certs)?;
    let certs_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let cert_path = certs_dir.join("server.crt");
    let client_cfg = make_client_config(&cert_path);
    let mut endpoint = Endpoint::client(bind_addr)?;
    endpoint.set_default_client_config(client_cfg);
    Ok(endpoint)
}

/// Constructs a QUIC endpoint configured to listen for incoming connections on a certain address
/// and port.
///
/// ## Returns
///
/// - a stream of incoming QUIC connections
/// - server certificate serialized into DER format
#[allow(unused)]
pub fn make_server_endpoint(
    bind_addr: SocketAddr,
) -> Result<(Endpoint, CertificateDer<'static>), Box<dyn Error + Send + Sync + 'static>> {
    //let (server_config, server_cert) = configure_server()?;
    let (server_config, server_cert) = make_server_config()?;
    let endpoint = Endpoint::server(server_config, bind_addr)?;
    Ok((endpoint, server_cert))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();

    let server_addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 5000);
    let (endpoint, _server_cert) = make_server_endpoint(server_addr)?;
    // accept a single connection
    //let endpoint2 = endpoint.clone();
    let handle = tokio::spawn(async move {
        loop {
            let incoming_conn = endpoint.accept().await.unwrap();
            println!("accepted");
            let conn = incoming_conn.await.unwrap();
            println!(
                "[server] connection accepted: addr={}",
                conn.remote_address()
            );
            tokio::spawn(async move {
                loop {
                    let (mut s, mut r) = conn.open_bi().await.unwrap();
                    s.write(&[1, 2, 3]).await.unwrap();
                    let mut target = vec![0; 128];
                    if let Some(count) = r.read(&mut target).await.unwrap() {
                        println!("Read {count} bytes");
                    }
                }
            });
        }
    });

    let endpoint = make_client_endpoint("0.0.0.0:0".parse().unwrap())?;
    // connect to server
    let connection = endpoint
        .connect(server_addr, "localhost")
        .unwrap()
        .await
        .unwrap();
    println!("[client] connected: addr={}", connection.remote_address());

    // Waiting for a stream will complete with an error when the server closes the connection
    let (mut _s, mut r) = connection.accept_bi().await.unwrap();
    let mut target = vec![0; 128];
    if let Some(count) = r.read(&mut target).await.unwrap() {
        println!("READ {count} {}", target[0]);
    }

    // Make sure the server has a chance to clean up
    endpoint.wait_idle().await;

    _ = handle.await.unwrap();
    Ok(())
}
