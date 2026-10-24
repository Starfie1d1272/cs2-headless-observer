import { snappyUncompressedLength } from '../../compression/wasm.js';
import { CSVCMsg_PacketEntities, type CSVCMsg_FullFrameSplit } from '../../ts-proto/netmessages.js';

/** Ordered, bounded ordinary-viewer full snapshots. Valve 0x18004ca50 / 0x180137a50. */
export class FullFrameAssembler {
	private tick = -1;
	private total = 0;
	private bytes = 0;
	private parts: Uint8Array[] = [];
	reset() {
		this.tick = -1;
		this.total = 0;
		this.bytes = 0;
		this.parts = [];
	}
	consume(msg: CSVCMsg_FullFrameSplit, uncompress: (input: Uint8Array) => Uint8Array) {
		const { tick, section, total, data } = msg;
		if (
			!Number.isInteger(tick) ||
			tick! < 0 ||
			!Number.isInteger(section) ||
			section! < 0 ||
			!Number.isInteger(total) ||
			total! < 1 ||
			total! > 4096 ||
			section! >= total! ||
			!data?.length
		)
			throw new Error('Invalid full-frame section');
		if (tick !== this.tick) {
			if (section !== 0) return null;
			this.reset();
			this.tick = tick!;
			this.total = total!;
		}
		if (total !== this.total || section !== this.parts.length) {
			this.reset();
			return null;
		}
		if (this.bytes + data.length > 8 * 1024 ** 2) throw new Error('Compressed full-frame budget');
		this.parts.push(Uint8Array.from(data));
		this.bytes += data.length;
		if (this.parts.length !== total) return null;
		const joined = new Uint8Array(this.bytes);
		let offset = 0;
		for (const part of this.parts) {
			joined.set(part, offset);
			offset += part.length;
		}
		const sourceTick = this.tick;
		this.reset();
		const size = snappyUncompressedLength(joined);
		if (size < 1 || size > 16 * 1024 ** 2) throw new Error('Full-frame output budget');
		const decoded = uncompress(joined);
		if (decoded.length !== size) throw new Error('Full-frame decompression length');
		const packet = CSVCMsg_PacketEntities.decode(decoded);
		if (packet.server_tick !== sourceTick || packet.legacy_is_delta === true)
			throw new Error('Full-frame identity');
		return { tick: sourceTick, packet };
	}
}
