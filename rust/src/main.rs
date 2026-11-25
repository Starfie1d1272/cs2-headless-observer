use clap::{Parser, Subcommand};
use std::path::PathBuf;

use cs2_headless_observer::session::replay::run_replay;
use cs2_headless_observer::session::supervisor::{run_managed, ManagedArgs};

#[derive(Parser)]
#[command(
    name = "cs2-headless-observer",
    version,
    about = "CS2 GOTV Headless Observer v4"
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    #[arg(long)]
    managed: bool,
    #[arg(long)]
    native: Option<PathBuf>,
    #[arg(long)]
    steam_api: Option<PathBuf>,
    #[arg(long, default_value = "ahead")]
    source_role: String,
    #[arg(long)]
    source_id: Option<String>,
    #[arg(long)]
    host_version: Option<u32>,
    #[arg(long)]
    output: Option<PathBuf>,
    #[arg(long)]
    follow_source: bool,
    #[arg(long)]
    seconds: Option<f64>,
}

#[derive(Subcommand)]
enum Commands {
    Replay {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        host_version: u32,
        #[arg(long)]
        output: PathBuf,
    },
}

fn main() {
    let cli = Cli::parse();
    let result = match cli.command {
        Some(Commands::Replay {
            input,
            host_version,
            output,
        }) => run_replay(&input, host_version, &output),
        None => {
            if !cli.managed {
                eprintln!("Use --managed or replay subcommand");
                std::process::exit(2);
            }
            let Some(native) = cli.native else {
                eprintln!("--native is required in --managed mode");
                std::process::exit(2);
            };
            let Some(host_version) = cli.host_version else {
                eprintln!("--host-version is required in --managed mode");
                std::process::exit(2);
            };
            let Some(output) = cli.output else {
                eprintln!("--output is required in --managed mode");
                std::process::exit(2);
            };
            let source_id = cli
                .source_id
                .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
            run_managed(ManagedArgs {
                native,
                steam_api: cli.steam_api,
                source_role: cli.source_role,
                source_id,
                host_version,
                output,
                follow_source: cli.follow_source,
                seconds: cli.seconds,
            })
        }
    };

    if let Err(err) = result {
        eprintln!("observer-error: {err}");
        std::process::exit(1);
    }
}
