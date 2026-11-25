pub mod abi;
pub mod password;

#[derive(Debug, Clone)]
pub struct ReceivedPacket {
    pub data: Vec<u8>,
    pub reliable: bool,
    pub dequeue_ns: u64,
    pub sdk_queue_age_us: Option<i64>,
}

pub trait ObserverPort {
    fn state(&self) -> i32;
    fn failure(&self) -> i32;
    fn remote_end_reason(&self) -> i32;
    fn pump(&mut self, now_ms: u64);
    fn remote_id(&self) -> u64;
    fn local_id(&self) -> u64;
    fn accept_server_auth2(&mut self) -> Result<(), String>;
    fn request_ticket(&mut self) -> Result<(), String>;
    fn with_auth<F, R>(&self, f: F) -> Result<R, String>
    where
        F: FnOnce(&[u8]) -> Result<R, String>;
    fn send(&mut self, data: &[u8], flags: i32) -> Result<(), String>;
    fn receive(&mut self) -> Result<Option<ReceivedPacket>, String>;
    fn close(&mut self);
}
