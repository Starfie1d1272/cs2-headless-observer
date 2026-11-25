use std::fmt;

use super::bits::{
    encode_pb_bytes, encode_pb_varint, encode_varint, read_varint, scalar_bytes, scalar_varint,
    wire_fields, WireError,
};

#[derive(Clone, PartialEq, Eq)]
pub struct Challenge {
    pub number: u32,
    pub server_steam_id: u64,
    pub secure: bool,
    pub context: Vec<u8>,
    pub auth_protocol: u32,
}

impl fmt::Debug for Challenge {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Challenge")
            .field("secure", &self.secure)
            .field("auth_protocol", &self.auth_protocol)
            .field("context_len", &self.context.len())
            .finish()
    }
}

pub fn parse_challenge_body(body: &[u8]) -> Result<Challenge, WireError> {
    if body.len() < 20 || body.len() > 2400 {
        return Err(WireError::ChallengeSize);
    }
    let challenge = u32::from_le_bytes(body[0..4].try_into().unwrap());
    let auth = u32::from_le_bytes(body[4..8].try_into().unwrap());
    let key_size = u16::from_le_bytes(body[8..10].try_into().unwrap());
    let server = u64::from_le_bytes(body[10..18].try_into().unwrap());
    let secure = body[18];

    if auth != 2 && auth != 3 {
        return Err(WireError::UnsupportedAuthProtocol);
    }
    if auth == 3 && key_size != 0 {
        return Err(WireError::InvalidSteamKeySize);
    }
    if secure != 0 && secure != 1 {
        return Err(WireError::InvalidSecureFlag);
    }
    let context = &body[19..];
    if !context.ends_with(b"\0") || context[..context.len() - 1].contains(&0) {
        return Err(WireError::ChallengeContextBoundary);
    }
    Ok(Challenge {
        number: challenge,
        server_steam_id: server,
        secure: if auth == 3 { secure != 0 } else { false },
        context: context[..context.len() - 1].to_vec(),
        auth_protocol: auth,
    })
}

pub fn connect_payload(
    host_version: u32,
    challenge: &Challenge,
    auth_steam: &[u8],
    player_name: &str,
    encrypted_password: Option<&[u8]>,
    reservation_cookie: u64,
    low_violence: bool,
) -> Result<Vec<u8>, WireError> {
    if (challenge.auth_protocol != 2 && challenge.auth_protocol != 3)
        || (challenge.auth_protocol == 3 && (auth_steam.len() <= 8 || auth_steam.len() > 2048))
        || (challenge.auth_protocol == 2 && !auth_steam.is_empty())
    {
        return Err(WireError::AuthPayloadSizeOrProtocol);
    }
    let name = player_name.as_bytes();
    if name.is_empty() || name.len() > 127 || name.contains(&0) {
        return Err(WireError::PlayerNameBoundary);
    }
    if let Some(pw) = encrypted_password {
        if pw.len() != 96 {
            return Err(WireError::EncryptedPasswordSize);
        }
    }
    let mut payload = Vec::with_capacity(256);
    encode_pb_varint(1, host_version as u64, &mut payload);
    encode_pb_varint(2, challenge.auth_protocol as u64, &mut payload);
    encode_pb_varint(3, challenge.number as u64, &mut payload);
    payload.push(0x21);
    payload.extend_from_slice(&reservation_cookie.to_le_bytes());
    encode_pb_varint(5, if low_violence { 1 } else { 0 }, &mut payload);
    if let Some(pw) = encrypted_password {
        encode_pb_bytes(6, pw, &mut payload);
    }
    let mut cvar_name = Vec::with_capacity(2 + name.len());
    encode_pb_bytes(1, name, &mut cvar_name);
    encode_pb_bytes(7, &cvar_name, &mut payload);
    if challenge.auth_protocol == 3 {
        encode_pb_bytes(8, auth_steam, &mut payload);
    }
    encode_pb_bytes(9, &challenge.context, &mut payload);
    if payload.len() > 2400 {
        return Err(WireError::ConnectSizeLimit);
    }
    Ok(payload)
}

pub fn connect_inner_message(payload: &[u8]) -> Result<Vec<u8>, WireError> {
    if payload.len() >= 2400 {
        return Err(WireError::ConnectPayloadBoundary);
    }
    let mut msg = Vec::with_capacity(5 + 5 + payload.len());
    msg.extend_from_slice(b"\xff\xff\xff\xffk");
    encode_varint(payload.len() as u64, &mut msg);
    msg.extend_from_slice(payload);
    if msg.len() > 1200 {
        return Err(WireError::ObservedConnectWriterBudget);
    }
    Ok(msg)
}

pub fn initial_challenge_request(challenge_number: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity(5 + 17 + 1);
    out.extend_from_slice(b"\xff\xff\xff\xffq");
    let tag = format!("connect0x{challenge_number:08X}");
    out.extend_from_slice(tag.as_bytes());
    out.push(0);
    out
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectionInner {
    pub addon_name_bytes: Option<usize>,
}

pub fn parse_connection_inner(message: &[u8]) -> Result<ConnectionInner, WireError> {
    if !message.starts_with(b"\xff\xff\xff\xffB") || message.len() < 16 || message.len() > 256 {
        return Err(WireError::ConnectionInnerPrefixOrBudget);
    }
    let mut pos = 5usize;
    let size = read_varint(message, &mut pos)? as usize;
    if size > 0x7FFF_FFFF || pos > 10 || pos + size > message.len() {
        return Err(WireError::ConnectionInnerLength);
    }
    let end = pos + size;
    if message.len() != end.max(16) || message[end..].iter().any(|&b| b != b'0') {
        return Err(WireError::ConnectionInnerPadding);
    }
    let decoded = wire_fields(&message[pos..end], 65535)?;
    let addon = scalar_bytes(&decoded, 1)?;
    Ok(ConnectionInner {
        addon_name_bytes: addon.map(|b| b.len()),
    })
}

pub fn signon_payload(state: u32, spawn_count: u32) -> Result<Vec<u8>, WireError> {
    if !(2..=6).contains(&state) {
        return Err(WireError::UnsupportedAckState);
    }
    let mut out = Vec::with_capacity(12);
    encode_pb_varint(1, state as u64, &mut out);
    encode_pb_varint(2, spawn_count as u64, &mut out);
    encode_pb_varint(3, 0, &mut out);
    Ok(out)
}

pub fn signon_message_bits(state: u32, spawn_count: u32) -> Result<(Vec<u8>, usize), WireError> {
    let payload = signon_payload(state, spawn_count)?;
    let mut data = Vec::with_capacity(5 + payload.len());
    encode_varint(payload.len() as u64, &mut data);
    data.extend_from_slice(&payload);
    let bit_count = 6 + 8 * data.len();
    let total_bytes = bit_count.div_ceil(8);
    let mut out = vec![0u8; total_bytes];
    out[0] = 7;
    for (i, &b) in data.iter().enumerate() {
        out[i] |= b << 6;
        if i + 1 < total_bytes {
            out[i + 1] |= b >> 2;
        }
    }
    Ok((out, bit_count))
}

#[derive(Debug, Clone)]
pub struct SignonSequence {
    pub state: u32,
    pub received_state: u32,
    pub full_from_entities: bool,
    pub spawn_count: Option<u32>,
    pub closed: bool,
    pub initialization_blocked: bool,
}

impl Default for SignonSequence {
    fn default() -> Self {
        Self::new()
    }
}

impl SignonSequence {
    pub fn new() -> Self {
        Self {
            state: 2,
            received_state: 2,
            full_from_entities: false,
            spawn_count: None,
            closed: false,
            initialization_blocked: false,
        }
    }

    pub fn server_info(&mut self, server_count: u32) -> Result<(), WireError> {
        if let Some(prev) = self.spawn_count {
            if server_count != prev {
                self.closed = true;
                return Err(WireError::Signon(
                    "server-count-changed-new-instance-required",
                ));
            }
        }
        self.spawn_count = Some(server_count);
        Ok(())
    }

    pub fn receive(&mut self, message: &[u8]) -> Result<u32, WireError> {
        if self.closed {
            return Err(WireError::Signon("connection-closed"));
        }
        let decoded = wire_fields(message, 65535)?;
        let state = scalar_varint(&decoded, 1)?;
        let count = scalar_varint(&decoded, 2)?;
        let (Some(state_u64), Some(count_u64)) = (state, count) else {
            return Err(WireError::Signon("missing-or-unsupported-signon"));
        };
        if !(2..=7).contains(&state_u64) || count_u64 > u32::MAX as u64 {
            return Err(WireError::Signon("missing-or-unsupported-signon"));
        }
        let state = state_u64 as u32;
        let count = count_u64 as u32;
        if let Some(sc) = self.spawn_count {
            if count != sc && count != 0xFFFF_FFFF {
                return Err(WireError::Signon("spawn-count-mismatch"));
            }
        }
        if state == 6 && self.state == 6 && self.full_from_entities {
            self.received_state = state;
            return Ok(state);
        }
        if state < self.state || (state >= 3 && state == self.state) {
            return Err(WireError::Signon("nonadvancing-signon"));
        }
        if state > self.state + 1 {
            return Err(WireError::Signon("skipped-signon-initialization"));
        }
        self.state = state;
        self.received_state = state;
        if state == 3 || state == 5 {
            self.initialization_blocked = true;
        }
        if state == 7 {
            self.closed = true;
        }
        Ok(state)
    }

    pub fn finish_new(&mut self) -> Result<(), WireError> {
        if self.closed || self.state != 3 || self.spawn_count.is_none() {
            return Err(WireError::Signon("new-initialization-order"));
        }
        if !self.initialization_blocked {
            return Err(WireError::Signon("new-initialization-already-completed"));
        }
        self.initialization_blocked = false;
        Ok(())
    }

    pub fn finish_spawn(&mut self) -> Result<(), WireError> {
        if self.closed || self.state != 5 || self.spawn_count.is_none() {
            return Err(WireError::Signon("spawn-initialization-order"));
        }
        self.initialization_blocked = false;
        Ok(())
    }

    pub fn finish_full_snapshot(&mut self) -> Result<(), WireError> {
        if self.closed
            || self.state != 5
            || self.spawn_count.is_none()
            || self.initialization_blocked
        {
            return Err(WireError::Signon("full-snapshot-initialization-order"));
        }
        self.state = 6;
        self.full_from_entities = true;
        Ok(())
    }

    pub fn acknowledgement(&self) -> Result<(u32, Vec<u8>), WireError> {
        if self.closed {
            return Err(WireError::Signon("connection-closed"));
        }
        if self.state == 2 && self.spawn_count.is_none() {
            return Ok((7, signon_payload(2, 0xFFFF_FFFF)?));
        }
        let sc = self
            .spawn_count
            .ok_or(WireError::Signon("serverinfo-missing"))?;
        if self.initialization_blocked {
            return Err(WireError::Signon("client-initialization-not-implemented"));
        }
        Ok((7, signon_payload(self.state, sc)?))
    }
}
