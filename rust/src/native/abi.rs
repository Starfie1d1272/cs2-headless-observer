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
        f.write_str("native-start-failed")
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

struct NativeFns {
    state: FnState,
    failure: FnFailure,
    remote_end_reason: FnRemoteEndReason,
    pump: FnPump,
    remote_id: FnRemoteId,
    local_id: FnLocalId,
    accept_server_auth2: FnAcceptAuth2,
    request_ticket: FnRequestTicket,
    auth: FnAuth,
    send: FnSend,
    receive_many: FnReceiveMany,
    release_received: FnReleaseReceived,
    close: FnClose,
}

unsafe fn load_fn<T: Copy>(lib: &Library, name: &[u8]) -> Result<T, libloading::Error> {
    let sym: Symbol<T> = lib.get(name)?;
    Ok(*sym)
}

pub struct NativePort {
    _steam_lib: Option<Library>,
    _lib: Library,
    fns: NativeFns,
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

        let abi_ver: FnAbiVersion = unsafe { load_fn(&lib, b"observer_abi_version\0")? };
        if unsafe { abi_ver() } != 4 {
            return Err("native-abi-version".into());
        }

        let create: FnCreate = unsafe { load_fn(&lib, b"observer_create\0")? };
        let boot_failure_fn: FnBootFailure = unsafe { load_fn(&lib, b"observer_boot_failure\0")? };
        let init_result_fn: FnInitResult = unsafe { load_fn(&lib, b"observer_init_result\0")? };

        let fns = unsafe {
            NativeFns {
                state: load_fn(&lib, b"observer_state\0")?,
                failure: load_fn(&lib, b"observer_failure\0")?,
                remote_end_reason: load_fn(&lib, b"observer_remote_end_reason\0")?,
                pump: load_fn(&lib, b"observer_pump\0")?,
                remote_id: load_fn(&lib, b"observer_remote_id\0")?,
                local_id: load_fn(&lib, b"observer_local_id\0")?,
                accept_server_auth2: load_fn(&lib, b"observer_accept_server_auth2\0")?,
                request_ticket: load_fn(&lib, b"observer_request_ticket\0")?,
                auth: load_fn(&lib, b"observer_auth\0")?,
                send: load_fn(&lib, b"observer_send\0")?,
                receive_many: load_fn(&lib, b"observer_receive_many\0")?,
                release_received: load_fn(&lib, b"observer_release_received\0")?,
                close: load_fn(&lib, b"observer_close\0")?,
            }
        };

        let c_endpoint = CString::new(endpoint)?;
        let handle = unsafe { create(c_endpoint.as_ptr(), now_ms) };
        if handle.is_null() {
            return Err(Box::new(NativeStartError {
                boot_code: unsafe { boot_failure_fn() },
                init_result: unsafe { init_result_fn() },
            }));
        }

        Ok(Self {
            _steam_lib: steam_lib,
            _lib: lib,
            fns,
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
        unsafe { (self.fns.state)(self.handle) }
    }

    fn failure(&self) -> i32 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe { (self.fns.failure)(self.handle) }
    }

    fn remote_end_reason(&self) -> i32 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe { (self.fns.remote_end_reason)(self.handle) }
    }

    fn pump(&mut self, now_ms: u64) {
        if !self.handle.is_null() {
            unsafe { (self.fns.pump)(self.handle, now_ms) };
        }
    }

    fn remote_id(&self) -> u64 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe { (self.fns.remote_id)(self.handle) }
    }

    fn local_id(&self) -> u64 {
        if self.handle.is_null() {
            return 0;
        }
        unsafe { (self.fns.local_id)(self.handle) }
    }

    fn accept_server_auth2(&mut self) -> Result<(), String> {
        if unsafe { (self.fns.accept_server_auth2)(self.handle) } != 1 {
            return Err("native-auth2-phase-invalid".into());
        }
        Ok(())
    }

    fn request_ticket(&mut self) -> Result<(), String> {
        if unsafe { (self.fns.request_ticket)(self.handle) } != 1 {
            return Err("native-ticket-request-failed".into());
        }
        Ok(())
    }

    fn with_auth<F, R>(&self, consume: F) -> Result<R, String>
    where
        F: FnOnce(&[u8]) -> Result<R, String>,
    {
        let mut size: u32 = 0;
        let ptr = unsafe { (self.fns.auth)(self.handle, &mut size) };
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
        if unsafe { (self.fns.send)(self.handle, data.as_ptr(), data.len() as u32, flags) } != 1 {
            return Err("native-send-failed".into());
        }
        Ok(())
    }

    fn receive(&mut self) -> Result<Option<ReceivedPacket>, String> {
        if self.batch_index == self.batch_count {
            let count = unsafe {
                (self.fns.receive_many)(
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
            unsafe { (self.fns.release_received)(self.handle) };
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
            unsafe { (self.fns.close)(self.handle) };
            self.handle = std::ptr::null_mut();
        }
    }
}

impl Drop for NativePort {
    fn drop(&mut self) {
        self.close();
    }
}
