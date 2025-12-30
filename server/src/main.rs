use anyhow::Result;
use num_enum::IntoPrimitive;
use num_enum::TryFromPrimitive;
use quinn::RecvStream;
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
use tokio::time::timeout;
use tracing::debug;
use tracing::trace;
use tracing::warn;
use tracing_subscriber::EnvFilter;

// macro_rules! encode_uints {
//     ($buf:expr, $($val:expr),+) => {{
//         let count = [$(stringify!($val)),+].len();
//         _ = rmp::encode::write_array_len(&mut $buf, count as u32);
//         $(
//             _ = rmp::encode::write_uint(&mut $buf, $val as u64);
//         )+
//     }};
// }

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

#[repr(u8)]
#[derive(IntoPrimitive, TryFromPrimitive)]
enum NetCmd {
    Pass = 0,
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
    MoveTo(u32, u32),
    Attack(RelPos),
}

struct Player {
    x: u32,
    y: u32,
}

struct GameState {
    players: HashMap<u64, Player>,
}

/// Create a framed msgpack packet
macro_rules! make_packet {
    ($($val:expr),+) => {{
        let count = [$(stringify!($val)),+].len();
        let mut buf : Vec<u8> = vec![0,0];
        _ = rmp::encode::write_array_len(&mut buf, count as u32);
        $(
            _ = rmp::encode::write_uint(&mut buf, $val as u64);
        )+
        let t = u16::to_be_bytes((buf.len() - 2) as u16);
        buf[0..2].copy_from_slice(&t);
        buf
    }};
}

async fn read_packet(recv_stream: &mut RecvStream, target: &mut [u8]) -> Result<usize> {
    let mut t = [0u8; 2];
    recv_stream.read_exact(&mut t).await?;
    let len = u16::from_be_bytes(t) as usize;
    recv_stream.read_exact(&mut target[..len]).await?;
    Ok(len)
}

fn decode_packet(source: &[u8]) -> Vec<i64> {
    let mut cursor = Cursor::new(source);
    let len = rmp::decode::read_array_len(&mut cursor).unwrap();
    let mut result = Vec::new();
    for _ in 0..len {
        let val: i64 = rmp::decode::read_int(&mut cursor).unwrap();
        result.push(val);
    }
    debug!("Decoded packet {result:?}");
    result
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .init();

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
            let conn = incoming_conn.await.unwrap();
            debug!("Accepted cient from {}", conn.remote_address());
            let player_count = player_count.clone();
            let mut turn_rx = turn_rx.clone();
            let cmd_tx = cmd_tx.clone();
            // Client loop
            tokio::spawn(async move {
                let (mut send_stream, mut recv_stream) = conn.open_bi().await.unwrap();
                let mut target = vec![0; 128];
                let id = player_count.fetch_add(1, Ordering::SeqCst);
                cmd_tx.send((id, Command::AddPlayer)).await.unwrap();

                let buf = make_packet!(NetCmd::YouAre, id);
                send_stream.write(&buf).await.unwrap();
                debug!("Player {id} loop starting");

                while turn_rx.changed().await.is_ok() {
                    let (turn, data) = turn_rx.borrow_and_update().clone();
                    if !data.is_empty() {
                        let res = send_stream.write(&data).await;
                        if let Err(_) = res {
                            cmd_tx.send((id, Command::TimeoutPlayer)).await.unwrap();
                            break;
                        }
                    }
                    debug!("Player {id} turn {turn}");
                    // let bytes = rmp_serde::to_vec(&msg).unwrap();
                    // send_stream.write(&bytes).await.unwrap();
                    let mut command: Option<Command> = None;
                    while command.is_none() {
                        if let Ok(res) = timeout(
                            Duration::from_secs(1),
                            read_packet(&mut recv_stream, &mut target),
                        )
                        .await
                        {
                            match res {
                                Ok(count) => {
                                    trace!("Read {:x?}", &target[0..count]);
                                    let packet = decode_packet(&target[..count]);
                                    match NetCmd::try_from(packet[0] as u8) {
                                        Ok(NetCmd::MoveTo) => {
                                            let x = packet[1] as u32;
                                            let y = packet[2] as u32;
                                            trace!("Move To {x} {y}");
                                            command = Some(Command::MoveTo(x, y));
                                        }
                                        Ok(NetCmd::Pass) => {
                                            command = Some(Command::Wait);
                                        }
                                        Ok(NetCmd::Turn) => {}
                                        _ => {}
                                    }
                                }
                                Err(e) => {
                                    warn!("Error: {:?}", e);
                                    command = Some(Command::TimeoutPlayer);
                                }
                            }
                        } else {
                            // Timeout
                            warn!("Timeout");
                            command = Some(Command::TimeoutPlayer);
                        }
                    }
                    if let Some(command) = command {
                        trace!("Client {id} command {command:?}");
                        cmd_tx.send((id, command)).await.unwrap();
                    }
                }
            });
        }
    });

    // Server main loop
    let state = state.clone();
    tokio::spawn(async move {
        let mut ids = HashSet::new();
        ids.insert(0);
        let mut turn = 0;
        loop {
            if state.lock().unwrap().players.is_empty() {
                tokio::time::sleep(Duration::from_millis(100)).await;
            } else {
                debug!("Turn {turn}");
                let buf = make_packet!(NetCmd::Turn, turn);
                turn_tx.send((turn, buf)).unwrap();
                turn += 1;
            }
            // Get all client commands
            loop {
                let (id, cmd) = cmd_rx.recv().await.unwrap();
                debug!("Client {id} reported {:?}", cmd);
                {
                    let mut s = state.lock().unwrap();
                    match cmd {
                        Command::AddPlayer => _ = s.players.insert(id, Player { x: 0, y: 0 }),
                        Command::TimeoutPlayer => {
                            _ = s.players.remove(&id);
                            debug!("Removed player {id}");
                        }

                        Command::MoveTo(x, y) => {
                            let player = s.players.get_mut(&id).unwrap();
                            player.x = x;
                            player.y = y;
                            let _buf = make_packet!(NetCmd::MoveTo, id, player.x, player.y);
                        }
                        _ => (),
                    }
                }
                ids.insert(id);
                if ids.len() >= state.lock().unwrap().players.len() {
                    debug!("All clients reported");
                    // All clients have reported in
                    ids.clear();
                    break;
                }
            }
        }
    });

    // let endpoint = make_client_endpoint("0.0.0.0:0".parse()?)?;
    // // connect to server
    // let connection = endpoint.connect(server_addr, "localhost")?.await?;
    // println!("[client] connected: addr={}", connection.remote_address());
    //
    // // Waiting for a stream will complete with an error when the server closes the connection
    // let (mut s, mut r) = connection.accept_bi().await?;
    // let mut target = vec![0; 128];
    // if let Some(count) = r.read(&mut target).await? {
    //     println!("READ {count} {}", target[0]);
    //     //s.write(&target[0..1]).await?;
    // }
    //
    // // Make sure the server has a chance to clean up
    // endpoint.wait_idle().await;

    _ = handle.await?;
    Ok(())
}
