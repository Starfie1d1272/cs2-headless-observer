use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "cs2_obs_cli_test_{name}_{}_{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    dir
}

#[test]
fn test_managed_output_directory_unavailable() {
    let existing = temp_dir("existing_out");
    std::fs::create_dir_all(&existing).unwrap();

    let out = Command::new(env!("CARGO_BIN_EXE_cs2-headless-observer"))
        .args([
            "--managed",
            "--native",
            "nonexistent-native",
            "--host-version",
            "14192",
            "--output",
        ])
        .arg(&existing)
        .stdin(Stdio::null())
        .output()
        .unwrap();

    let _ = std::fs::remove_dir_all(&existing);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert_eq!(stderr.trim(), "output-directory-unavailable");
}

#[test]
fn test_managed_configuration_boundary() {
    let base = temp_dir("bad_cfg");
    std::fs::create_dir_all(&base).unwrap();
    let target_out = base.join("run");

    let mut child = Command::new(env!("CARGO_BIN_EXE_cs2-headless-observer"))
        .args([
            "--managed",
            "--native",
            "nonexistent-native",
            "--host-version",
            "14192",
            "--output",
        ])
        .arg(&target_out)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    {
        let stdin = child.stdin.as_mut().unwrap();
        stdin.write_all(b"not-valid-json\n").unwrap();
    }
    let out = child.wait_with_output().unwrap();

    let _ = std::fs::remove_dir_all(&base);
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert_eq!(stderr.trim(), "configuration-boundary");
}

#[test]
fn test_managed_rejects_removed_v2_flags() {
    for flag in ["--follow-source", "--source-role", "--source-id"] {
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_cs2-headless-observer"));
        cmd.arg("--managed").arg(flag);
        if flag != "--follow-source" {
            cmd.arg("val");
        }
        let out = cmd.output().unwrap();
        assert_eq!(out.status.code(), Some(2), "flag {flag} should exit 2");
    }
}

#[test]
fn test_managed_stdin_eof_stop_writes_v3_report() {
    let base = temp_dir("eof_stop");
    std::fs::create_dir_all(&base).unwrap();
    let target_out = base.join("run");

    let mut child = Command::new(env!("CARGO_BIN_EXE_cs2-headless-observer"))
        .args([
            "--managed",
            "--native",
            "nonexistent-native",
            "--host-version",
            "14192",
            "--output",
        ])
        .arg(&target_out)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    // Write valid config line and immediately close stdin (EOF).
    {
        let stdin = child.stdin.as_mut().unwrap();
        stdin
            .write_all(br#"{"endpoint":"127.0.0.1:27020","password":""}"#)
            .unwrap();
        stdin.write_all(b"\n").unwrap();
        stdin.flush().unwrap();
    }

    let out = child.wait_with_output().unwrap();
    let report_path = target_out.join("report.json");
    assert!(report_path.exists(), "report.json should be written");
    let report: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&report_path).unwrap()).unwrap();
    let _ = std::fs::remove_dir_all(&base);

    assert_eq!(report["schema"], "cs2-observer-report/3");
    if report["outcome"] == "stopped" {
        assert_eq!(report["reason"], "owner-stopped");
        assert_eq!(out.status.code(), Some(0));
    } else {
        assert_eq!(report["outcome"], "failed");
        assert_eq!(out.status.code(), Some(1));
    }
}
