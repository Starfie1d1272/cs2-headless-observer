use crate::wire::bits::BitReader;
use std::sync::OnceLock;

const MAX_DEPTH: usize = 10;
const STOP_SYMBOL: u8 = 39;

const FIELD_PATH_WEIGHTS: [u32; 40] = [
    36271, 10334, 1375, 646, 4128, 35, 3, 521, 2942, 560, 471, 10530, 251, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 310, 2, 0, 1837, 149, 300, 634, 0, 0, 1, 76, 271, 99, 25474,
];

#[derive(Clone)]
struct TreeNode {
    value: u16,
    weight: u32,
    left: Option<Box<TreeNode>>,
    right: Option<Box<TreeNode>>,
    leaf: bool,
}

struct HuffmanTables {
    primary: [u16; 256],
    long: Vec<u16>,
}

fn build_huffman_tables() -> HuffmanTables {
    let mut nodes: Vec<TreeNode> = FIELD_PATH_WEIGHTS
        .iter()
        .enumerate()
        .map(|(i, &w)| TreeNode {
            value: i as u16,
            weight: if w == 0 { 1 } else { w },
            left: None,
            right: None,
            leaf: true,
        })
        .collect();
    let mut next_id = nodes.len() as u16;
    while nodes.len() > 1 {
        nodes.sort_by(|a, b| a.weight.cmp(&b.weight).then_with(|| b.value.cmp(&a.value)));
        let left = nodes.remove(0);
        let right = nodes.remove(0);
        let parent = TreeNode {
            value: next_id,
            weight: left.weight + right.weight,
            left: Some(Box::new(left)),
            right: Some(Box::new(right)),
            leaf: false,
        };
        nodes.push(parent);
        next_id += 1;
    }
    let root = nodes.into_iter().next().unwrap();

    let mut primary = [0u16; 256];
    let mut long = vec![0u16; 1 << 17];
    let mut long_roots: Vec<(usize, &TreeNode)> = Vec::new();

    fn fill_primary<'a>(
        node: &'a TreeNode,
        code: usize,
        depth: usize,
        primary: &mut [u16; 256],
        long_roots: &mut Vec<(usize, &'a TreeNode)>,
    ) {
        if node.leaf {
            let count = 1usize << (8 - depth);
            let entry = ((depth as u16) << 6) | node.value;
            for i in 0..count {
                primary[code | (i << depth)] = entry;
            }
            return;
        }
        if depth == 8 {
            long_roots.push((code, node));
            return;
        }
        fill_primary(
            node.left.as_ref().unwrap(),
            code,
            depth + 1,
            primary,
            long_roots,
        );
        fill_primary(
            node.right.as_ref().unwrap(),
            code | (1 << depth),
            depth + 1,
            primary,
            long_roots,
        );
    }

    fn fill_long(node: &TreeNode, code: usize, depth: usize, long: &mut [u16]) {
        if node.leaf {
            let count = 1usize << (17 - depth);
            let entry = ((depth as u16) << 6) | node.value;
            for i in 0..count {
                long[code | (i << depth)] = entry;
            }
            return;
        }
        if depth >= 17 {
            return;
        }
        fill_long(node.left.as_ref().unwrap(), code, depth + 1, long);
        fill_long(
            node.right.as_ref().unwrap(),
            code | (1 << depth),
            depth + 1,
            long,
        );
    }

    fill_primary(&root, 0, 0, &mut primary, &mut long_roots);
    for (prefix, node) in long_roots {
        fill_long(node, prefix, 8, &mut long);
    }

    HuffmanTables { primary, long }
}

fn tables() -> &'static HuffmanTables {
    static TABLES: OnceLock<HuffmanTables> = OnceLock::new();
    TABLES.get_or_init(build_huffman_tables)
}

#[derive(Debug, Clone)]
struct PathState {
    path: [i32; MAX_DEPTH],
    last: usize,
}

impl PathState {
    fn new() -> Self {
        let mut path = [0i32; MAX_DEPTH];
        path[0] = -1;
        Self { path, last: 0 }
    }

    fn push_check(&self, count: usize) -> Result<(), String> {
        if self.last + 1 + count > MAX_DEPTH {
            return Err("Field path depth overflow".into());
        }
        Ok(())
    }

    fn pop(&mut self, count: usize) -> Result<(), String> {
        if count > self.last {
            return Err("Field path depth underflow".into());
        }
        for _ in 0..count {
            self.path[self.last] = 0;
            self.last -= 1;
        }
        Ok(())
    }
}

fn apply_op(op: u8, r: &mut BitReader<'_>, s: &mut PathState) -> Result<(), String> {
    if op > 39 {
        return Err("Invalid field path opcode".into());
    }
    if op == 39 {
        s.path = [0; MAX_DEPTH];
        s.path[0] = 32767;
        s.last = 0;
        return Ok(());
    }
    let fixed_push: usize = match op {
        5..=12 => 1,
        13 | 14 | 17 | 18 | 21 | 22 => 2,
        15 | 16 | 19 | 20 | 23 | 24 => 3,
        _ => 0,
    };
    if fixed_push > 0 {
        s.push_check(fixed_push)?;
    }
    if matches!(op, 27 | 28 | 37) && s.last < 1 {
        return Err("Field path depth underflow".into());
    }

    let map_err = |e: crate::wire::bits::WireError| e.to_string();

    match op {
        0 => s.path[s.last] += 1,
        1 => s.path[s.last] += 2,
        2 => s.path[s.last] += 3,
        3 => s.path[s.last] += 4,
        4 => s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32 + 5,
        5 => {
            s.last += 1;
            s.path[s.last] = 0;
        }
        6 => {
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
        }
        7 => {
            s.path[s.last] += 1;
            s.last += 1;
            s.path[s.last] = 0;
        }
        8 => {
            s.path[s.last] += 1;
            s.last += 1;
            s.path[s.last] = r.read_ubitvar_fp().map_err(map_err)? as i32;
        }
        9 => {
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] = 0;
        }
        10 => {
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32 + 2;
            s.last += 1;
            s.path[s.last] = r.read_ubitvar_fp().map_err(map_err)? as i32 + 1;
        }
        11 => {
            s.path[s.last] += r.read_bits(3).map_err(map_err)? as i32 + 2;
            s.last += 1;
            s.path[s.last] = r.read_bits(3).map_err(map_err)? as i32 + 1;
        }
        12 => {
            s.path[s.last] += r.read_bits(4).map_err(map_err)? as i32 + 2;
            s.last += 1;
            s.path[s.last] = r.read_bits(4).map_err(map_err)? as i32 + 1;
        }
        13 => {
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
        }
        14 => {
            s.last += 1;
            s.path[s.last] = r.read_bits(5).map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] = r.read_bits(5).map_err(map_err)? as i32;
        }
        15 => {
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            }
        }
        16 => {
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] = r.read_bits(5).map_err(map_err)? as i32;
            }
        }
        17 => {
            s.path[s.last] += 1;
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
        }
        18 => {
            s.path[s.last] += 1;
            s.last += 1;
            s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
        }
        19 => {
            s.path[s.last] += 1;
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            }
        }
        20 => {
            s.path[s.last] += 1;
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
            }
        }
        21 => {
            s.path[s.last] += r.read_ubitvar().map_err(map_err)? as i32 + 2;
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
        }
        22 => {
            s.path[s.last] += r.read_ubitvar().map_err(map_err)? as i32 + 2;
            s.last += 1;
            s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
            s.last += 1;
            s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
        }
        23 => {
            s.path[s.last] += r.read_ubitvar().map_err(map_err)? as i32 + 2;
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            }
        }
        24 => {
            s.path[s.last] += r.read_ubitvar().map_err(map_err)? as i32 + 2;
            for _ in 0..3 {
                s.last += 1;
                s.path[s.last] += r.read_bits(5).map_err(map_err)? as i32;
            }
        }
        25 => {
            let count = r.read_ubitvar().map_err(map_err)? as usize;
            s.push_check(count)?;
            s.path[s.last] += r.read_ubitvar().map_err(map_err)? as i32;
            for _ in 0..count {
                s.last += 1;
                s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32;
            }
        }
        26 => {
            for i in 0..=s.last {
                if r.read_bool().map_err(map_err)? {
                    s.path[i] += r.read_varint32().map_err(map_err)? + 1;
                }
            }
            let count = r.read_ubitvar().map_err(map_err)? as usize;
            s.push_check(count)?;
            for _ in 0..count {
                s.last += 1;
                s.path[s.last] = r.read_ubitvar_fp().map_err(map_err)? as i32;
            }
        }
        27 => {
            s.pop(1)?;
            s.path[s.last] += 1;
        }
        28 => {
            s.pop(1)?;
            s.path[s.last] += r.read_ubitvar_fp().map_err(map_err)? as i32 + 1;
        }
        29 => {
            s.pop(s.last)?;
            s.path[0] += 1;
        }
        30 => {
            s.pop(s.last)?;
            s.path[0] += r.read_ubitvar_fp().map_err(map_err)? as i32 + 1;
        }
        31 => {
            s.pop(s.last)?;
            s.path[0] += r.read_bits(3).map_err(map_err)? as i32 + 1;
        }
        32 => {
            s.pop(s.last)?;
            s.path[0] += r.read_bits(6).map_err(map_err)? as i32 + 1;
        }
        33 => {
            let count = r.read_ubitvar_fp().map_err(map_err)? as usize;
            s.pop(count)?;
            s.path[s.last] += 1;
        }
        34 => {
            let count = r.read_ubitvar_fp().map_err(map_err)? as usize;
            s.pop(count)?;
            s.path[s.last] += r.read_varint32().map_err(map_err)?;
        }
        35 => {
            let count = r.read_ubitvar_fp().map_err(map_err)? as usize;
            s.pop(count)?;
            for i in 0..=s.last {
                if r.read_bool().map_err(map_err)? {
                    s.path[i] += r.read_varint32().map_err(map_err)?;
                }
            }
        }
        36 => {
            for i in 0..=s.last {
                if r.read_bool().map_err(map_err)? {
                    s.path[i] += r.read_varint32().map_err(map_err)?;
                }
            }
        }
        37 => {
            s.path[s.last - 1] += 1;
        }
        38 => {
            for i in 0..=s.last {
                if r.read_bool().map_err(map_err)? {
                    s.path[i] += r.read_bits(4).map_err(map_err)? as i32 - 7;
                }
            }
        }
        _ => unreachable!(),
    }

    for i in 0..=s.last {
        s.path[i] = (s.path[i] as i16) as i32;
    }
    Ok(())
}

pub fn read_field_paths(
    reader: &mut BitReader<'_>,
    max_paths: usize,
    bit_budget: usize,
) -> Result<Vec<Vec<u16>>, String> {
    let initial_bits = reader.remaining_bits();
    if bit_budget > initial_bits {
        return Err("Invalid field-list bit boundary".into());
    }
    let tbl = tables();
    let mut state = PathState::new();
    let mut result = Vec::new();
    loop {
        let prefix = reader.peek_huffman_prefix() as usize;
        let mut code = tbl.primary[prefix];
        if code == 0 {
            let long_idx = reader.peek_huffman_code() as usize;
            code = tbl.long[long_idx];
        }
        let width = (code >> 6) as usize;
        let op = (code & 63) as u8;
        if !(1..=17).contains(&width) || op > STOP_SYMBOL {
            return Err("Invalid Huffman field path".into());
        }
        if (initial_bits - reader.remaining_bits()) + width > bit_budget {
            return Err("Truncated field-list code".into());
        }
        reader.consume_bits(width).map_err(|e| e.to_string())?;
        apply_op(op, reader, &mut state)?;
        if initial_bits - reader.remaining_bits() > bit_budget {
            return Err("Truncated field-list payload".into());
        }
        if state.path[0] == 32767 {
            return Ok(result);
        }
        let mut path = Vec::with_capacity(state.last + 1);
        for &v in state.path.iter().take(state.last + 1) {
            if !(0..=32767).contains(&v) {
                return Err("Invalid resolved field path".into());
            }
            path.push(v as u16);
        }
        if result.len() >= max_paths {
            return Err("Field-list budget exceeded".into());
        }
        result.push(path);
    }
}
