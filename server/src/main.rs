use anyhow::Result;
use num_enum::FromPrimitive;
use num_enum::IntoPrimitive;
use num_enum::TryFromPrimitive;
use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use quinn::{ClientConfig, Endpoint, ServerConfig};
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use rustls::{RootCertStore, ServerConfig as RustlsServerConfig};
use rustls_pemfile::{certs, private_key};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufReader, Cursor};
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use std::{
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::sync::watch;
use tokio::time::{Instant, sleep_until, timeout};

#[macro_use]
extern crate num_derive;

fn load_certs(path: &Path) -> Vec<CertificateDer<'static>> {
    let mut reader = BufReader::new(File::open(path).unwrap());
    certs(&mut reader).map(|c| c.unwrap()).collect()
}

fn load_key(path: &Path) -> PrivateKeyDer<'static> {
    let mut reader = BufReader::new(File::open(path).unwrap());
    private_key(&mut reader).unwrap().unwrap()
}

fn make_server_config() -> Result<(ServerConfig, CertificateDer<'static>)> {
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
pub fn make_client_endpoint(bind_addr: SocketAddr) -> Result<Endpoint> {
    //let client_cfg = configure_client(server_certs)?;
    let certs_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let cert_path = certs_dir.join("server.crt");
    let client_cfg = make_client_config(&cert_path);
    let mut endpoint = Endpoint::client(bind_addr)?;
    endpoint.set_default_client_config(client_cfg);
    Ok(endpoint)
}

/// Constructs a QUIC endpoint configured to listen for incoming connections
/// on a certain address and port.
///
/// ## Returns
///
/// - a stream of incoming QUIC connections
/// - server certificate serialized into DER format
#[allow(unused)]
pub fn make_server_endpoint(bind_addr: SocketAddr) -> Result<(Endpoint, CertificateDer<'static>)> {
    //let (server_config, server_cert) = configure_server()?;
    let (server_config, server_cert) = make_server_config()?;
    let endpoint = Endpoint::server(server_config, bind_addr)?;
    Ok((endpoint, server_cert))
}

#[derive(Serialize, Deserialize)]
struct Msg {
    id: u32,
    x: i32,
    y: i32,
    enabled: bool,
}

#[repr(u8)]
#[derive(IntoPrimitive, TryFromPrimitive)]
enum NetCmd {
    YouAre = 1,
    Turn = 2,
    MoveTo = 3,
}

type Dir = u8;
type RelPos = (u8, u8);
#[derive(Debug, Serialize, Deserialize, PartialEq)]
enum Command {
    Wait,
    AddPlayer,
    TimeoutPlayer,
    Move(Dir),
    MoveTo(u8, u8),
    Attack(RelPos),
}

struct Player {
    x: u32,
    y: u32,
}

struct GameState {
    players: HashMap<u64, Player>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();

    let server_addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 5000);
    let (endpoint, _server_cert) = make_server_endpoint(server_addr)?;

    let state = Arc::new(Mutex::new(GameState {
        players: HashMap::new(),
    }));

    // From ooordinator to all clients; turn no and bytes to send
    let (turn_tx, turn_rx) = watch::channel::<(usize, Vec<u8>)>((0, vec![]));

    // From client handler to coordinator
    let (cmd_tx, mut cmd_rx) = tokio::sync::mpsc::channel::<(u64, Command)>(128);

    // Server accept loop
    let handle = tokio::spawn(async move {
        let player_count: Arc<AtomicU64> = Arc::new(0.into());
        loop {
            let incoming_conn = endpoint.accept().await.unwrap();
            println!("accepted");
            let conn = incoming_conn.await.unwrap();
            println!(
                "[server] connection accepted: addr={}",
                conn.remote_address()
            );
            let player_count = player_count.clone();
            let mut turn_rx = turn_rx.clone();
            let cmd_tx = cmd_tx.clone();
            // Client loop
            tokio::spawn(async move {
                let (mut send_stream, mut recv_stream) = conn.open_bi().await.unwrap();
                let mut target = vec![0; 128];
                let id = player_count.fetch_add(1, Ordering::SeqCst);
                cmd_tx.send((id, Command::AddPlayer)).await.unwrap();

                let mut buf = Vec::with_capacity(16);
                _ = rmp::encode::write_array_len(&mut buf, 2);
                _ = rmp::encode::write_u8(&mut buf, NetCmd::YouAre as u8);
                _ = rmp::encode::write_u64(&mut buf, id);
                send_stream.write(&buf).await.unwrap();
                println!("Player {id} loop starting");

                while turn_rx.changed().await.is_ok() {
                    let (turn, data) = turn_rx.borrow_and_update().clone();
                    if !data.is_empty() {
                        let res = send_stream.write(&data).await;
                        if let Err(e) = res {
                            cmd_tx.send((id, Command::TimeoutPlayer)).await.unwrap();
                            break;
                        }
                    }
                    println!("Player {id} turn {turn}");
                    // let bytes = rmp_serde::to_vec(&msg).unwrap();
                    // send_stream.write(&bytes).await.unwrap();
                    if let Ok(res) =
                        timeout(Duration::from_secs(1), recv_stream.read(&mut target)).await
                    {
                        match res {
                            Ok(count) => {
                                if let Some(count) = count {
                                    println!("Read {:x?}", &target[0..count]);
                                    let mut cursor = Cursor::new(&target[0..count]);
                                    let len = rmp::decode::read_array_len(&mut cursor).unwrap();
                                    println!("Len {len}");
                                    let cmd: u8 = rmp::decode::read_int(&mut cursor).unwrap();
                                    println!("CMD {cmd}");
                                    match NetCmd::try_from(cmd) {
                                        Ok(NetCmd::MoveTo) => {
                                            let x = rmp::decode::read_u32(&mut cursor).unwrap();
                                            let y = rmp::decode::read_u32(&mut cursor).unwrap();
                                        }
                                        Ok(NetCmd::Turn) => {}
                                        _ => {}
                                    }
                                }
                            }
                            Err(e) => {
                                println!("Error: {:?}", e);
                                cmd_tx.send((id, Command::TimeoutPlayer)).await.unwrap();
                                break;
                            }
                        }
                    } else {
                        // Timeout
                        println!("Timeout");
                        cmd_tx.send((id, Command::TimeoutPlayer)).await.unwrap();
                        break;
                    }
                    println!("{id} send Wait");
                    cmd_tx.send((id, Command::Wait)).await.unwrap();
                }
            });
        }
    });

    // Server main loop
    let state = state.clone();
    tokio::spawn(async move {
        let mut ids = HashSet::new();
        ids.insert(0);
        let mut buf = Vec::with_capacity(1024);
        let mut t = Instant::now() + Duration::from_millis(1000);
        for turn in 1.. {
            sleep_until(t).await;
            t += Duration::from_millis(1000);
            println!("SRV: Turn {turn}");
            _ = rmp::encode::write_array_len(&mut buf, 2);
            _ = rmp::encode::write_u8(&mut buf, NetCmd::Turn as u8);
            _ = rmp::encode::write_u64(&mut buf, turn as u64);
            turn_tx.send((turn, buf.clone())).unwrap();
            buf.clear();
            loop {
                let (id, cmd) = cmd_rx.recv().await.unwrap();
                println!("SRV: {id} reported {:?}", cmd);
                {
                    let mut s = state.lock().unwrap();
                    match cmd {
                        Command::AddPlayer => _ = s.players.insert(id, Player { x: 0, y: 0 }),
                        Command::TimeoutPlayer => {
                            _ = s.players.remove(&id);
                            println!("Removed player {id}");
                        }

                        Command::MoveTo(x, y) => {
                            let player = s.players.get_mut(&id).unwrap();
                            player.x = x as u32;
                            player.y = y as u32;
                            _ = rmp::encode::write_array_len(&mut buf, 2);
                            _ = rmp::encode::write_u8(&mut buf, NetCmd::MoveTo as u8);
                            _ = rmp::encode::write_u64(&mut buf, id);
                            _ = rmp::encode::write_u32(&mut buf, player.x);
                            _ = rmp::encode::write_u32(&mut buf, player.y);
                        }
                        _ => (),
                    }
                }
                ids.insert(id);
                if ids.len() >= state.lock().unwrap().players.len() {
                    println!("All reported");
                    // All clients have reported in
                    ids.clear();
                    break;
                }
            }
        }
    });

    let endpoint = make_client_endpoint("0.0.0.0:0".parse()?)?;
    // connect to server
    let connection = endpoint.connect(server_addr, "localhost")?.await?;
    println!("[client] connected: addr={}", connection.remote_address());

    // Waiting for a stream will complete with an error when the server closes the connection
    let (mut s, mut r) = connection.accept_bi().await?;
    let mut target = vec![0; 128];
    if let Some(count) = r.read(&mut target).await? {
        println!("READ {count} {}", target[0]);
        //s.write(&target[0..1]).await?;
    }

    // Make sure the server has a chance to clean up
    endpoint.wait_idle().await;

    _ = handle.await?;
    Ok(())
}
