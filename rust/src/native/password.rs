use std::sync::atomic::{compiler_fence, Ordering};
use std::sync::OnceLock;

use crate::wire::bits::WireError;

/// Zeroizes its buffer on explicit wipe or Drop using volatile writes.
#[derive(Clone, Default)]
pub struct SecretBytes {
    buf: Vec<u8>,
}

impl SecretBytes {
    pub fn new(bytes: Vec<u8>) -> Self {
        Self { buf: bytes }
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.buf
    }

    pub fn is_empty(&self) -> bool {
        self.buf.is_empty()
    }

    pub fn len(&self) -> usize {
        self.buf.len()
    }

    pub fn zeroize(&mut self) {
        for b in &mut self.buf {
            unsafe {
                std::ptr::write_volatile(b, 0);
            }
        }
        compiler_fence(Ordering::SeqCst);
        self.buf.clear();
    }
}

impl Drop for SecretBytes {
    fn drop(&mut self) {
        self.zeroize();
    }
}

impl std::fmt::Debug for SecretBytes {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SecretBytes")
            .field("len", &self.buf.len())
            .finish()
    }
}

const MOD: [[u32; 4]; 4] = [
    [333, 313, 505, 369],
    [379, 375, 319, 391],
    [361, 445, 451, 397],
    [397, 425, 395, 505],
];

const XOR: [[u32; 4]; 4] = [
    [0x83, 0x85, 0x9B, 0xCD],
    [0xCC, 0xA7, 0xAD, 0x41],
    [0x4B, 0x2E, 0xD4, 0x33],
    [0xEA, 0xCB, 0x2E, 0x04],
];

const PERM: [u32; 32] = [
    1, 128, 1024, 8192, 524288, 2097152, 16777216, 1073741824, 8, 32, 256, 16384, 65536, 8388608,
    67108864, 536870912, 4, 16, 512, 32768, 131072, 4194304, 134217728, 268435456, 2, 64, 2048,
    4096, 262144, 1048576, 33554432, 2147483648,
];

const ROT: [usize; 16] = [0, 1, 2, 3, 2, 1, 3, 0, 1, 3, 2, 0, 3, 1, 0, 2];

fn gf_mul(mut a: u32, mut b: u32, modulus: u32) -> u32 {
    let mut result = 0u32;
    while b != 0 {
        if (b & 1) != 0 {
            result ^= a;
        }
        a <<= 1;
        b >>= 1;
        if a >= 256 {
            a ^= modulus;
        }
    }
    result
}

fn sboxes() -> &'static [[u32; 1024]; 4] {
    static SBOX: OnceLock<[[u32; 1024]; 4]> = OnceLock::new();
    SBOX.get_or_init(|| {
        let mut tables = [[0u32; 1024]; 4];
        for b in 0..4 {
            for (index, slot) in tables[b].iter_mut().enumerate() {
                let col = ((index >> 1) & 255) as u32;
                let row = (index & 1) | ((index & 512) >> 8);
                let value = col ^ XOR[b][row];
                let modulus = MOD[b][row];
                let sq = gf_mul(value, value, modulus);
                let cube = gf_mul(value, sq, modulus);
                let sixth = gf_mul(cube, cube, modulus);
                let seventh = gf_mul(value, sixth, modulus) << (24 - 8 * b);
                let mut acc = 0u32;
                for (bit, &p) in PERM.iter().enumerate() {
                    if (seventh & (1u32 << bit)) != 0 {
                        acc += p;
                    }
                }
                *slot = acc;
            }
        }
        tables
    })
}

fn schedule(key: &[u8; 8]) -> [[u32; 3]; 16] {
    let mut words = [
        u16::from_be_bytes([key[6], key[7]]),
        u16::from_be_bytes([key[4], key[5]]),
        u16::from_be_bytes([key[2], key[3]]),
        u16::from_be_bytes([key[0], key[1]]),
    ];
    let mut sched = [[0u32; 3]; 16];
    for (r_idx, &rotation) in ROT.iter().enumerate() {
        let mut subkey = [0u32; 3];
        for step in 0..15 {
            let slot = step % 3;
            for column in 0..4 {
                let index = (rotation + column) & 3;
                let bit = (words[index] & 1) as u32;
                subkey[slot] = (subkey[slot] << 1) | bit;
                words[index] = (words[index] >> 1) | (((bit ^ 1) as u16) << 15);
            }
        }
        sched[r_idx] = subkey;
    }
    sched
}

fn ice_round(value: u32, key: &[u32; 3], tables: &[[u32; 1024]; 4]) -> u32 {
    let mut left = ((value >> 16) & 1023) | (value.rotate_right(14) & 0xFFC00);
    let mut right = (value & 1023) | ((value << 2) & 0xFFC00);
    let salt = key[2] & (left ^ right);
    left ^= salt ^ key[0];
    right ^= salt ^ key[1];
    tables[0][(left >> 10) as usize]
        | tables[1][(left & 1023) as usize]
        | tables[2][(right >> 10) as usize]
        | tables[3][(right & 1023) as usize]
}

pub fn ice1_encrypt(key: [u8; 8], plaintext: &[u8]) -> Result<Vec<u8>, WireError> {
    if !plaintext.len().is_multiple_of(8) {
        return Err(WireError::EncryptedPasswordSize);
    }
    let sched = schedule(&key);
    let tables = sboxes();
    let mut result = Vec::with_capacity(plaintext.len());
    for chunk in plaintext.as_chunks::<8>().0 {
        let mut left = u32::from_be_bytes(chunk[0..4].try_into().unwrap());
        let mut right = u32::from_be_bytes(chunk[4..8].try_into().unwrap());
        for i in (0..16).step_by(2) {
            left ^= ice_round(right, &sched[i], tables);
            right ^= ice_round(left, &sched[i + 1], tables);
        }
        result.extend_from_slice(&right.to_be_bytes());
        result.extend_from_slice(&left.to_be_bytes());
    }
    Ok(result)
}

pub fn transform_password(password: &[u8], challenge: u32) -> Result<Option<Vec<u8>>, WireError> {
    if password.len() > 95 || password.contains(&0) {
        return Err(WireError::EncryptedPasswordSize);
    }
    if password.is_empty() {
        return Ok(None);
    }
    let mut key = [0u8; 8];
    key[0..4].copy_from_slice(&(challenge ^ 0x5EF8CE12).to_le_bytes());
    key[4..8].copy_from_slice(&(challenge ^ 0xAA98E42C).to_le_bytes());
    let mut padded = [0u8; 96];
    padded[..password.len()].copy_from_slice(password);
    let enc = ice1_encrypt(key, &padded)?;
    for b in &mut padded {
        unsafe { std::ptr::write_volatile(b, 0) };
    }
    for b in &mut key {
        unsafe { std::ptr::write_volatile(b, 0) };
    }
    compiler_fence(Ordering::SeqCst);
    Ok(Some(enc))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_password_oracle_and_zeroize() {
        let mut pw = SecretBytes::new(b"secret".to_vec());
        let out = transform_password(pw.as_slice(), 0x12345678)
            .unwrap()
            .unwrap();
        assert_eq!(out.len(), 96);
        assert!(transform_password(b"", 0x12345678).unwrap().is_none());
        assert!(transform_password(&[b'a'; 96], 0).is_err());
        assert!(transform_password(b"a\0b", 0).is_err());
        pw.zeroize();
        assert!(pw.is_empty());
    }
}
