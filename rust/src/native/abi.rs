use std::ffi::{c_char, c_int, c_void, CString};
use std::path::Path;
use std::time::Instant;

use libloading::{Library, Symbol};

use super::{ObserverPort, ReceivedPacket};
use crate::wire::bits::MAX_BYTES;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct CReceived {
    pub data: *const u8,
    pub sdk_queue_age_us: i64,
    pub size: u32,
    pub reliable: i32,
}

impl Default for CReceived {
    fn default() -> Self {
        Self {
            data: std::ptr::null(),
            sdk_queue_age_us: -1,
            size: 0,
            reliable: 0,
        }
    }
}

#[derive(Debug)]
pub struct NativeStartError {
    pub boot_code: i32,
    pub init_result: i32,
}

impl std::fmt::Display for NativeStartError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "native-start-failed (boot={}, init={})",
            self.boot_code, self.init_result
        )
    }
}

impl std::error::Error for NativeStartError {}

type FnAbiVersion = unsafe extern "C" fn() -> c_int;
type FnBootFailure = unsafe extern "C" fn() -> c_int;
type FnInitResult = unsafe extern "C" fn() -> c_int;
type FnCreate = unsafe extern "C" fn(*const c_char, u64) -> *mut c_void;
type FnState = unsafe extern "C" fn(*mut c_void) -> c_int;
type FnFailure = unsafe extern "C" fn(*mut c_void) -> c_int;
type FnRemoteEndReason = unsafe extern "C" fn(*mut c_void) -> c_int;
type FnPump = unsafe extern "C" fn(*mut c_void, u64);
type FnRemoteId = unsafe extern "C" fn(*mut c_void) -> u64;
type FnLocalId = unsafe extern "C" fn(*mut c_void) -> u64;
type FnAcceptAuth2 = unsafe extern "C" fn(*mut c_void) -> c_int;
type FnRequestTicket = unsafe extern "C" fn(*mut c_void) -> c_int;
type FnAuth = unsafe extern "C" fn(*mut c_void, *mut u32) -> *const u8;
type FnSend = unsafe extern "C" fn(*mut c_void, *const u8, u32, c_int) -> c_int;
type FnReceiveMany = unsafe extern "C" fn(*mut c_void, *mut CReceived, c_int) -> c_int;
type FnReleaseReceived = unsafe extern "C" fn(*mut c_void);
type FnClose = unsafe extern "C" fn(*mut c_void);

pub struct NativePort {
    _steam_lib: Option<Library>,
    lib: Library,
    handle: *mut c_void,
    batch: [CReceived; 8],
    batch_count: usize,
    batch_index: usize,
    dequeue_ns: u64,
    epoch: Instant,
}

impl NativePort {
    pub fn open(
        library_path: &Path,
        steam_api_path: Option<&Path>,
        endpoint: &str,
        now_ms: u64,
        epoch: Instant,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let steam_lib = if let Some(sa) = steam_api_path {
            let abs = sa.canonicalize()?;
            Some(unsafe { Library::new(&abs)? })
        } else {
            None
        };

        let abs_lib = library_path.canonicalize()?;
        let lib = unsafe { Library::new(&abs_lib)? };

        let abi_ver: Symbol<FnAbiVersion> = unsafe { lib.get(b"observer_abi_version")? };
        if unsafe { abi_ver() } != 4 {
            return Err("native-abi-version".into());
        }

        let create: Symbol<FnCreate> = unsafe { lib.get(b"observer_create")? };
        let c_endpoint = CString::new(endpoint)?;
        let handle = unsafe { create(c_endpoint.as_ptr(), now_ms) };
        if handle.is_null() {
            let boot_f: Symbol<FnBootFailure> = unsafe { lib.get(b"observer_boot_failure")? };
            let init_r: Symbol<FnInitResult> = unsafe { lib.get(b"observer_init_result")? };
            return Err(Box::new(NativeStartError {
                boot_code: unsafe { boot_f() },
                init_result: unsafe { init_r() },
            }));
        }

        Ok(Self {
            _steam_lib: steam_lib,
            lib,
            handle,
            batch: [CReceived::default(); 8],
            batch_count: 0,
            batch_index: 0,
            dequeue_ns: 0,
            epoch,
        })
    }
}

impl ObserverPort for NativePort {
    fn state(&self) -> i32 {
        if self.handle.is_null() {
            return 6;
        }
        unsafe {
            let f: Symbol<FnState> = self.lib.get(b"observer_state").unwrap();
            f(self.handle)
        }
    }

    fn failure(&self) -> i32 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe {
            let f: Symbol<FnFailure> = self.lib.get(b"observer_failure").unwrap();
            f(self.handle)
        }
    }

    fn remote_end_reason(&self) -> i32 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe {
            let f: Symbol<FnRemoteEndReason> = self.lib.get(b"observer_remote_end_reason").unwrap();
            f(self.handle)
        }
    }

    fn pump(&mut self, now_ms: u64) {
        if self.handle.is_null() {
            return;
        }
        unsafe {
            let f: Symbol<FnPump> = self.lib.get(b"observer_pump").unwrap();
            f(self.handle, now_ms);
        }
    }

    fn remote_id(&self) -> u64 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe {
            let f: Symbol<FnRemoteId> = self.lib.get(b"observer_remote_id").unwrap();
            f(self.handle)
        }
    }

    fn local_id(&self) -> u64 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe {
            let f: Symbol<FnLocalId> = self.lib.get(b"observer_local_id").unwrap();
            f(self.handle)
        }
    }

    fn accept_server_auth2(&mut self) -> Result<(), String> {
        let ok = unsafe {
            let f: Symbol<FnAcceptAuth2> = self
                .lib
                .get(b"observer_accept_server_auth2")
                .map_err(|e| e.to_string())?;
            f(self.handle)
        };
        if ok != 1 {
            return Err("native-auth2-phase-invalid".into());
        }
        Ok(())
    }

    fn request_ticket(&mut self) -> Result<(), String> {
        let ok = unsafe {
            let f: Symbol<FnRequestTicket> = self
                .lib
                .get(b"observer_request_ticket")
                .map_err(|e| e.to_string())?;
            f(self.handle)
        };
        if ok != 1 {
            return Err("native-ticket-request-failed".into());
        }
        Ok(())
    }

    fn with_auth<F, R>(&self, consume: F) -> Result<R, String>
    where
        F: FnOnce(&[u8]) -> Result<R, String>,
    {
        let mut size: u32 = 0;
        let ptr = unsafe {
            let f: Symbol<FnAuth> = self.lib.get(b"observer_auth").map_err(|e| e.to_string())?;
            f(self.handle, &mut size)
        };
        if ptr.is_null() || size <= 8 || size > 2048 {
            return Err("native-ticket-not-ready".into());
        }
        let slice = unsafe { std::slice::from_raw_parts(ptr, size as usize) };
        consume(slice)
    }

    fn send(&mut self, data: &[u8], flags: i32) -> Result<(), String> {
        if data.is_empty() || data.len() > 512 * 1024 || !matches!(flags, 1 | 5 | 8) {
            return Err("native-send-boundary".into());
        }
        let ok = unsafe {
            let f: Symbol<FnSend> = self.lib.get(b"observer_send").map_err(|e| e.to_string())?;
            f(self.handle, data.as_ptr(), data.len() as u32, flags)
        };
        if ok != 1 {
            return Err("native-send-failed".into());
        }
        Ok(())
    }

    fn receive(&mut self) -> Result<Option<ReceivedPacket>, String> {
        if self.batch_index == self.batch_count {
            let count = unsafe {
                let f: Symbol<FnReceiveMany> = self
                    .lib
                    .get(b"observer_receive_many")
                    .map_err(|e| e.to_string())?;
                f(
                    self.handle,
                    self.batch.as_mut_ptr(),
                    self.batch.len() as c_int,
                )
            };
            self.dequeue_ns = self.epoch.elapsed().as_nanos() as u64;
            self.batch_index = 0;
            if count < 0 || (count as usize) > self.batch.len() {
                return Err("native-receive-failed".into());
            }
            self.batch_count = count as usize;
            if self.batch_count == 0 {
                return Ok(None);
            }
        }
        let item = self.batch[self.batch_index];
        if item.data.is_null()
            || item.size == 0
            || (item.size as usize) > MAX_BYTES
            || !matches!(item.reliable, 0 | 1)
        {
            return Err("native-receive-failed".into());
        }
        let data = unsafe { std::slice::from_raw_parts(item.data, item.size as usize) }.to_vec();
        self.batch_index += 1;
        if self.batch_index == self.batch_count {
            unsafe {
                let f: Symbol<FnReleaseReceived> = self
                    .lib
                    .get(b"observer_release_received")
                    .map_err(|e| e.to_string())?;
                f(self.handle);
            }
        }
        Ok(Some(ReceivedPacket {
            data,
            reliable: item.reliable != 0,
            dequeue_ns: self.dequeue_ns,
            sdk_queue_age_us: if item.sdk_queue_age_us < 0 {
                None
            } else {
                Some(item.sdk_queue_age_us)
            },
        }))
    }

    fn close(&mut self) {
        if !self.handle.is_null() {
            if let Ok(f) = unsafe { self.lib.get::<FnClose>(b"observer_close") } {
                unsafe { f(self.handle) };
            }
            self.handle = std::ptr::null_mut();
        }
    }
}

impl Drop for NativePort {
    fn drop(&mut self) {
        self.close();
    }
}
