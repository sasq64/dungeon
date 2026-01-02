use anyhow::Result;
use num_enum::IntoPrimitive;
use num_enum::TryFromPrimitive;
use quinn::Connection;
use quinn::crypto::rustls::{QuicClientConfig, QuicServerConfig};
use quinn::{ClientConfig, Endpoint, ServerConfig};
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use rustls::{RootCertStore, ServerConfig as RustlsServerConfig};
use rustls_pemfile::{certs, private_key};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs::File;
use std::io::{BufReader, Cursor};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use std::{
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::select;
use tokio::sync::mpsc;
use tokio::sync::watch;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tracing::{debug, trace, warn};
use tracing_subscriber::EnvFilter;
use tracing_subscriber::fmt::FmtContext;
use tracing_subscriber::fmt::FormatEvent;
use tracing_subscriber::fmt::FormatFields;
use tracing_subscriber::fmt::format;
use tracing_subscriber::registry::LookupSpan;

struct MyFormat;

impl<S, N> FormatEvent<S, N> for MyFormat
where
    S: tracing::Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    fn format_event(
        &self,
        ctx: &FmtContext<'_, S, N>,
        mut writer: format::Writer<'_>,
        event: &tracing::Event<'_>,
    ) -> fmt::Result {
        let meta = event.metadata();

        write!(&mut writer, "{} [{}]: ", meta.level(), meta.target())?;
        if let Some(scope) = ctx.event_scope() {
            for span in scope.from_root() {
                write!(writer, "{}", span.name())?;
            }
        }

        ctx.field_format().format_fields(writer.by_ref(), event)?;
        //ctx.format_fields(writer, event)?;
        writeln!(writer)
    }
}
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
        .with_single_cert(cert_chain, key)?;
    rustls_config.alpn_protocols = vec![b"h3".to_vec()];

    let quic_crypto = QuicServerConfig::try_from(rustls_config)?;
    let mut server_config = ServerConfig::with_crypto(Arc::new(quic_crypto));
    let transport_config = Arc::get_mut(&mut server_config.transport).unwrap();
    transport_config.max_idle_timeout(Some(Duration::from_secs(60).try_into()?));
    Ok((server_config, server_cert))
}

fn make_client_config(cert_path: &Path) -> Result<ClientConfig> {
    let certs = load_certs(cert_path);

    let mut roots = RootCertStore::empty();
    for cert in certs {
        roots.add(cert)?;
    }

    let mut rustls = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();

    rustls.alpn_protocols = vec![b"h3".to_vec()];
    let quic_crypto = QuicClientConfig::try_from(rustls)?;

    Ok(ClientConfig::new(Arc::new(quic_crypto)))
}

#[allow(unused)]
pub fn make_client_endpoint(bind_addr: SocketAddr) -> Result<Endpoint> {
    //let client_cfg = configure_client(server_certs)?;
    let certs_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let cert_path = certs_dir.join("server.crt");
    let client_cfg = make_client_config(&cert_path)?;
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
    PlayerJoin = 4,
    PlayerLeave = 5,
}

#[derive(Debug)]
enum ServerCommand {
    Wait,
    AddPlayer(mpsc::Sender<ClientCommand>),
    TimeoutPlayer,
    MoveTo(u32, u32),
    Done(usize),
}

#[derive(Debug)]
enum ClientCommand {
    Packets(Vec<u8>),
    JoinGroup(u64, tokio::sync::watch::Receiver<(usize, Vec<u8>)>),
    Turn(usize),
}

#[derive(Debug)]
struct Player {
    x: u32,
    y: u32,
    moved: bool,
    sender: mpsc::Sender<ClientCommand>,
    turn: usize,
}

struct GameState {
    players: HashMap<u64, Player>,
}

/// Create a framed msgpack packet
macro_rules! make_packet {
    ($($val:expr),+) => {
        {
            let count = [$(stringify!($val)),+].len();
            let mut buf : Vec<u8> = vec![0,0];
            _ = rmp::encode::write_array_len(&mut buf, count as u32);
            $(
                _ = rmp::encode::write_uint(&mut buf, $val as u64);
            )+
            let t = u16::to_be_bytes((buf.len() - 2).try_into().unwrap());
            buf[0..2].copy_from_slice(&t);
            buf
        }
    };
}

macro_rules! make_packet_to {
    ($target:expr, $($val:expr),+) => {
        {
            let count = [$(stringify!($val)),+].len();
            let start = $target.len();
            $target.push(0);
            $target.push(0);
            _  = rmp::encode::write_array_len($target, count as u32);
            $(
                _ = rmp::encode::write_uint($target, $val as u64);
            )+
            let t = u16::to_be_bytes(($target.len() - start - 2).try_into().unwrap());
            $target[start..start+2].copy_from_slice(&t);
        }
    };
}

async fn read_packet(recv_stream: &mut quinn::RecvStream, target: &mut [u8]) -> Result<usize> {
    let mut t = [0u8; 2];
    recv_stream.read_exact(&mut t).await?;
    let len = u16::from_be_bytes(t) as usize;
    trace!(target: "Client", "Got packet header: {} bytes", len);
    recv_stream.read_exact(&mut target[..len]).await?;
    trace!(target: "Client", "Got packet");
    Ok(len)
}

fn decode_packet(source: &[u8]) -> Result<Vec<i64>> {
    let mut cursor = Cursor::new(source);
    let len = rmp::decode::read_array_len(&mut cursor)?;
    let mut result = Vec::new();
    for _ in 0..len {
        let val: i64 = rmp::decode::read_int(&mut cursor)?;
        result.push(val);
    }
    debug!(target: "Client", "Decoded packet {result:?}");
    Ok(result)
}

#[derive(Debug)]
struct Client {
    conn: Connection,
    player_count: Arc<AtomicU64>,
    turn_rx: Option<watch::Receiver<(usize, Vec<u8>)>>,
    cmd_tx: mpsc::Sender<(u64, ServerCommand)>,
    client_rx: mpsc::Receiver<ClientCommand>,
    client_tx: mpsc::Sender<ClientCommand>,
}

const CLIENT: &str = "Client";

impl Client {
    async fn run(mut self) -> Result<()> {
        //let (client_tx, mut client_rx) = tokio::sync::mpsc::channel::<Vec<u8>>(16);
        let (mut send_stream, mut recv_stream) = self.conn.open_bi().await?;
        let mut target = vec![0; 128];
        let id = self.player_count.fetch_add(1, Ordering::SeqCst);
        self.cmd_tx
            .send((id, ServerCommand::AddPlayer(self.client_tx)))
            .await?;

        let buf = make_packet!(NetCmd::YouAre, id);
        send_stream.write(&buf).await?;
        debug!(target: "Client", "Player {id} loop starting");
        let mut connected = true;

        let mut turn = 0xffffffff;

        while connected {
            if let Some(ref mut turn_rx) = self.turn_rx {
                trace!(target: CLIENT, "Wating for turn watch");
                // turn_rx.changed().await?;
                let (t, data) = turn_rx.borrow_and_update().clone();
                turn = t;
                if !data.is_empty() {
                    trace!(target: CLIENT, "Sending turn data to peer");
                    if send_stream.write_all(&data).await.is_err() {
                        self.cmd_tx.send((id, ServerCommand::TimeoutPlayer)).await?;
                        warn!(target: CLIENT, "Send failed");
                        break;
                    }
                }
            }

            trace!(target: CLIENT, "Waiting for server commands");
            let mut got_turn = false;
            while !got_turn {
                let cmd = self.client_rx.recv().await.unwrap();
                trace!(target: CLIENT, "Command {cmd:?} from server");
                match cmd {
                    ClientCommand::Packets(data) => {
                        trace!(target: CLIENT, "Sending packet with {} bytes", data.len());
                        if !data.is_empty() && send_stream.write_all(&data).await.is_err() {
                            self.cmd_tx.send((id, ServerCommand::TimeoutPlayer)).await?;
                            warn!(target: CLIENT, "Send failed");
                            break;
                        }
                    }
                    ClientCommand::JoinGroup(_id, watch) => {
                        self.turn_rx = Some(watch);
                    }
                    ClientCommand::Turn(nt) => {
                        turn = nt;
                        got_turn = true;
                    }
                }
            }
            let buf = make_packet!(NetCmd::Turn, turn);
            send_stream.write(&buf).await?;
            turn += 1;

            if !connected {
                warn!(target: CLIENT, "Send failed");
                break;
            }

            self.cmd_tx.send((id, ServerCommand::Wait)).await?;

            let mut command: Option<ServerCommand> = None;
            while command.is_none() {
                trace!(target: CLIENT, "Reading socket");
                if let Ok(res) = timeout(
                    Duration::from_secs(600),
                    read_packet(&mut recv_stream, &mut target),
                )
                .await
                {
                    match res {
                        Ok(count) => {
                            trace!(target: CLIENT, "Read {:x?}", &target[0..count]);
                            let packet = decode_packet(&target[..count])?;
                            if let Ok(cmd) = NetCmd::try_from(packet[0] as u8) {
                                match cmd {
                                    NetCmd::MoveTo => {
                                        let x = packet[1] as u32;
                                        let y = packet[2] as u32;
                                        trace!(target: CLIENT, "Got packet MoveTo {x} {y}");
                                        command = Some(ServerCommand::MoveTo(x, y));
                                    }
                                    NetCmd::Pass => {
                                        command = Some(ServerCommand::Wait);
                                    }
                                    NetCmd::Turn => {}
                                    _ => {}
                                }
                            } else {
                                warn!("Illegal packet cmd from client {id}");
                                connected = false;
                            }
                        }
                        Err(e) => {
                            warn!(target: CLIENT, "Error: {:?}", e);
                            command = Some(ServerCommand::TimeoutPlayer);
                            connected = false;
                        }
                    }
                } else {
                    // Timeout
                    warn!(target: CLIENT, "Read timed out");
                    command = Some(ServerCommand::TimeoutPlayer);
                    connected = false;
                }
            }
            if let Some(command) = command {
                trace!(target: CLIENT, "Client {id} produced command {command:?}");
                self.cmd_tx.send((id, command)).await?;
                if connected {
                    trace!(target: CLIENT, "Client {id} Done (turn {turn})");
                    self.cmd_tx.send((id, ServerCommand::Done(turn))).await?;
                }
            }
        }
        debug!("Client {id} exit loop");
        Ok(())
    }
}

struct Server {
    turn_tx: tokio::sync::watch::Sender<(usize, Vec<u8>)>,
    cmd_rx: tokio::sync::mpsc::Receiver<(u64, ServerCommand)>,
}

impl Server {
    async fn run(mut self) -> Result<()> {
        let mut state = GameState {
            players: HashMap::new(),
        };

        //let mut ids = HashSet::new();
        // let mut turn = 0;
        //loop {
        // debug!("Turn {turn} starting");
        // let mut output = Vec::new();
        // for (id, player) in &mut state.players {
        //     if player.moved {
        //         player.moved = false;
        //         trace!("Player {id} moved");
        //         make_packet_to!(&mut output, NetCmd::MoveTo, *id, player.x, player.y);
        //     }
        // }
        // make_packet_to!(&mut output, NetCmd::Turn, turn);
        // trace!("Send turn {turn}");
        // self.turn_tx.send((turn, output)).unwrap();
        // trace!("Send done");

        // Get all client commands
        loop {
            trace!("Reading client channel");
            let (id, cmd) = self.cmd_rx.recv().await.unwrap();
            trace!("Client {id} reported {:?}", cmd);
            {
                match cmd {
                    ServerCommand::AddPlayer(sender) => {
                        let new_player = Player {
                            x: 0,
                            y: 0,
                            moved: false,
                            sender,
                            turn: 0,
                        };
                        //let buf = make_packet!(NetCmd::PlayerJoin, id, 1, 0xffffff);
                        //out_data.extend_from_slice(&buf);
                        for (id, _player) in state.players.iter() {
                            let buf = make_packet!(NetCmd::PlayerJoin, *id, 1, 0xffffff);
                            // TODO: Dont await on loop
                            new_player
                                .sender
                                .send(ClientCommand::Packets(buf))
                                .await
                                .unwrap();
                        }
                        new_player
                            .sender
                            .send(ClientCommand::Turn(0))
                            .await
                            .unwrap();
                        _ = state.players.insert(id, new_player);
                    }
                    ServerCommand::TimeoutPlayer => {
                        _ = state.players.remove(&id);
                        debug!("Removed player {id}");
                    }
                    ServerCommand::Done(done_turn) => {
                        trace!("Done turn {done_turn}");
                        //assert!(done_turn == turn);
                        //ids.insert(id);
                        let player = state.players.get_mut(&id).unwrap();
                        player.turn += 1;
                        player
                            .sender
                            .send(ClientCommand::Turn(player.turn))
                            .await
                            .unwrap();
                    }

                    ServerCommand::MoveTo(x, y) => {
                        let player = state.players.get_mut(&id).unwrap();
                        player.x = x;
                        player.y = y;
                        player.moved = true;
                        let packet = make_packet!(NetCmd::MoveTo, id, player.x, player.y);
                        for (id, player) in &mut state.players {
                            trace!("Sending Move {x} {y} to cliend {id}");
                            player
                                .sender
                                .send(ClientCommand::Packets(packet.clone()))
                                .await
                                .unwrap();
                        }
                    }
                    _ => (),
                }
            }
            // trace!("{} {}", ids.len(), state.players.len());
            // if ids.len() >= state.players.len() {
            //     debug!("All clients done");
            //     // All clients have reported in
            //     turn += 1;
            //     ids.clear();
            //     break;
            // }
        }
        //}
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        //.event_format(MyFormat)
        .with_target(true)
        .compact()
        .with_env_filter(EnvFilter::from_default_env())
        .init();

    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();

    let server_addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 5000);
    let (endpoint, _server_cert) = make_server_endpoint(server_addr)?;

    // From ooordinator to all clients; turn no and bytes to send
    let (turn_tx, turn_rx) = watch::channel::<(usize, Vec<u8>)>((0, vec![]));

    // From client handler to coordinator
    let (cmd_tx, cmd_rx) = tokio::sync::mpsc::channel::<(u64, ServerCommand)>(128);

    // Server accept loop
    let handle = tokio::spawn(async move {
        let player_count: Arc<AtomicU64> = Arc::new(0.into());
        let mut client_set = JoinSet::<Result<()>>::new();
        loop {
            select! {
                incoming_conn = endpoint.accept() => {
                    if let Some(incoming_conn) = incoming_conn {
                        // TODO: Handle connection timeout
                        let conn = incoming_conn.await.unwrap();
                        debug!("Accepted cient from {}", conn.remote_address());
                        // From coordinator to client handler
                        let (client_tx, client_rx) =
                            tokio::sync::mpsc::channel::<ClientCommand>(128);
                        let client = Client {
                            conn,
                            player_count: player_count.clone(),
                            turn_rx: None,
                            cmd_tx: cmd_tx.clone(),
                            client_rx,
                            client_tx,
                        };
                        client_set.spawn(client.run());
                    }
                }
                res = client_set.join_next() => {
                    if let Some(res) = res {
                        debug!("Client future ended: {res:?}");
                    }
                }
            }
        }
    });

    let server = Server { turn_tx, cmd_rx };

    tokio::spawn(server.run());

    _ = handle.await?;
    Ok(())
}
