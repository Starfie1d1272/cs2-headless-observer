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
    #[arg(long)]
    host_version: Option<u32>,
    #[arg(long)]
    output: Option<PathBuf>,
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
    match cli.command {
        Some(Commands::Replay {
            input,
            host_version,
            output,
        }) => {
            if let Err(err) = run_replay(&input, host_version, &output) {
                eprintln!("observer-error: {err}");
                std::process::exit(1);
            }
        }
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
            if let Err(err) = run_managed(ManagedArgs {
                native,
                steam_api: cli.steam_api,
                host_version,
                output,
                seconds: cli.seconds,
            }) {
                if !err.report_written {
                    eprintln!("{}", err.reason);
                }
                std::process::exit(1);
            }
        }
    }
}
