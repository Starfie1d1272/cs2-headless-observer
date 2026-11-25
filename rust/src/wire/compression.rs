use super::bits::{WireError, MAX_BYTES};

/// Bounded independent LZ4 block decompression with exact expected output size.
pub fn lz4_block(data: &[u8], expected_size: usize) -> Result<Vec<u8>, WireError> {
    if data.is_empty() || data.len() > MAX_BYTES || expected_size > MAX_BYTES {
        return Err(WireError::Lz4Budget);
    }
    if expected_size == 0 {
        if data == [0] {
            return Ok(Vec::new());
        }
        return Err(WireError::Lz4Budget);
    }
    let out = lz4_flex::block::decompress(data, expected_size)
        .map_err(|e| WireError::Lz4Failed(e.to_string()))?;
    if out.len() != expected_size {
        return Err(WireError::Lz4Failed("output-size-mismatch".into()));
    }
    Ok(out)
}

/// Validate raw Snappy without allocating its claimed output.
/// Returns None if not a valid Snappy stream (caller falls back to raw).
pub fn snappy_uncompressed_size(data: &[u8]) -> Option<usize> {
    let mut p = 0usize;
    let mut size: u64 = 0;
    let mut shift = 0u32;
    let mut done = false;
    for i in 0..5 {
        let byte = *data.get(p)?;
        p += 1;
        if i == 4 && byte > 15 {
            return None;
        }
        size += ((byte & 127) as u64) << shift;
        if byte & 128 == 0 {
            done = true;
            break;
        }
        shift += 7;
    }
    if !done || size > (64 * 1024 * 1024) as u64 {
        return None;
    }
    let size = size as usize;
    let mut written = 0usize;
    while p < data.len() {
        let tag = data[p];
        p += 1;
        let kind = tag & 3;
        let length: usize;
        if kind == 0 {
            let mut l = (tag >> 2) as usize;
            if l < 60 {
                l += 1;
            } else {
                let n = l - 59;
                if p + n > data.len() {
                    return None;
                }
                let mut val = 0usize;
                for i in 0..n {
                    val |= (data[p + i] as usize) << (i * 8);
                }
                p += n;
                l = val + 1;
            }
            if p + l > data.len() {
                return None;
            }
            p += l;
            length = l;
        } else {
            let offset: usize;
            if kind == 1 {
                let low = *data.get(p)? as usize;
                p += 1;
                length = 4 + (((tag >> 2) & 7) as usize);
                offset = (((tag & 224) as usize) << 3) | low;
            } else {
                let n = if kind == 2 { 2 } else { 4 };
                if p + n > data.len() {
                    return None;
                }
                let mut off = 0usize;
                for i in 0..n {
                    off |= (data[p + i] as usize) << (i * 8);
                }
                p += n;
                length = 1 + ((tag >> 2) as usize);
                offset = off;
            }
            if offset == 0 || offset > written {
                return None;
            }
        }
        written = written.checked_add(length)?;
        if written > size {
            return None;
        }
    }
    if written == size {
        Some(size)
    } else {
        None
    }
}

/// Decompress a Snappy-compressed string table or fallback to raw copy if not Snappy.
pub fn snappy_decompress(data: &[u8], capacity: Option<usize>) -> Result<Vec<u8>, WireError> {
    let size = snappy_uncompressed_size(data);
    let cap = capacity.unwrap_or_else(|| size.unwrap_or(data.len()));
    if cap > 64 * 1024 * 1024 {
        return Err(WireError::SnappyFailed("table-decompression-budget".into()));
    }
    let Some(expected) = size else {
        if data.len() > cap {
            return Err(WireError::SnappyFailed("raw-table-capacity".into()));
        }
        return Ok(data.to_vec());
    };
    if expected > cap {
        return Err(WireError::SnappyFailed("snappy-table-capacity".into()));
    }
    let out = snap::raw::Decoder::new()
        .decompress_vec(data)
        .map_err(|e| WireError::SnappyFailed(e.to_string()))?;
    if out.len() != expected {
        return Err(WireError::SnappyFailed("snappy-output-size".into()));
    }
    Ok(out)
}

/// Valve LZSS decompression used in SpawnGroup resource manifests.
pub fn expand_lzss(data: &[u8]) -> Result<Vec<u8>, WireError> {
    if data.len() <= 8 || &data[0..4] != b"LZSS" {
        return Err(WireError::ManifestCompression("header"));
    }
    let expected = u32::from_le_bytes(data[4..8].try_into().unwrap()) as usize;
    if expected == 0 || expected > MAX_BYTES {
        return Err(WireError::ManifestCompression("expanded-budget"));
    }
    let mut output = Vec::with_capacity(expected);
    let mut cursor = 8usize;
    while cursor < data.len() {
        let commands = data[cursor];
        cursor += 1;
        for bit in 0..8 {
            let width = if (commands & (1 << bit)) != 0 { 2 } else { 1 };
            if cursor + width > data.len() {
                return Err(WireError::ManifestCompression("truncated"));
            }
            if width == 1 {
                if output.len() >= expected {
                    return Err(WireError::ManifestCompression("expanded-overflow"));
                }
                output.push(data[cursor]);
                cursor += 1;
                continue;
            }
            let b0 = data[cursor] as usize;
            let b1 = data[cursor + 1] as usize;
            cursor += 2;
            let count = (b1 & 15) + 1;
            if count == 1 {
                if output.len() != expected || cursor != data.len() {
                    return Err(WireError::ManifestCompression("end"));
                }
                return Ok(output);
            }
            let distance = ((b0 << 4) | (b1 >> 4)) + 1;
            if distance > output.len() || output.len() + count > expected {
                return Err(WireError::ManifestCompression("reference"));
            }
            for _ in 0..count {
                let b = output[output.len() - distance];
                output.push(b);
            }
        }
    }
    Err(WireError::ManifestCompression("missing-end"))
}
