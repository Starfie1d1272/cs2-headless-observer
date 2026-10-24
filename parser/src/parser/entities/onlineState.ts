/** Ordinary-viewer entity baselines; experimental, opt-in research path.
 * State transitions independently derived from the fixed official engine.
 */
import type { CSVCMsg_PacketEntities } from '../../ts-proto/netmessages.js';

type Frame = { members: Uint32Array; dormant: Uint32Array };
type Baseline = { classId: number; properties: Record<string, unknown> };
export class MissingEntityFrame extends Error {
	readonly tick: number;
	readonly deltaFrom: number;
	constructor(tick: number, deltaFrom: number) {
		super(`Missing entity frame ${deltaFrom} for ${tick}`);
		this.tick = tick;
		this.deltaFrom = deltaFrom;
	}
}
export class OnlineEntityState {
	private banks: [Map<number, Baseline>, Map<number, Baseline>] = [new Map(), new Map()];
	private frames = new Map<number, Frame>();
	private pending: {
		tick: number;
		bank: 0 | 1;
		update: boolean;
		delta: boolean;
		members: Uint32Array;
		dormant: Uint32Array;
		outOfPvs: Uint32Array;
		next: Map<number, Baseline> | null;
		overrides: Map<number, number>;
	} | null = null;
	private latest = -1;
	public waitingFull = false;
	private minimumFullTick = 0;
	get lastTick() {
		return this.latest;
	}
	begin(msg: CSVCMsg_PacketEntities, tick: number) {
		if (this.waitingFull && (msg.legacy_is_delta || tick < this.minimumFullTick)) return false;
		if (this.pending) throw new Error('Unfinished entity packet');
		if (!Number.isSafeInteger(tick) || tick < 0 || tick <= this.latest) throw new Error('Entity packet tick order');
		if (msg.server_tick !== undefined && msg.server_tick !== tick) throw new Error('Entity packet tick mismatch');
		const bank = msg.baseline ?? 0;
		if (bank !== 0 && bank !== 1) throw new Error('Invalid entity baseline bank');
		const delta = msg.legacy_is_delta === true;
		const from = msg.delta_from ?? -1;
		if (delta && (!Number.isInteger(from) || from < 0 || from >= tick))
			throw new Error('Invalid entity delta reference');
		const previous = delta ? this.frames.get(from) : undefined;
		if (delta && !previous) throw new MissingEntityFrame(tick, from);
		if (!delta) {
			this.banks = [new Map(), new Map()];
			this.frames.clear();
		}
		const overrides = new Map<number, number>();
		for (const item of msg.alternate_baselines ?? []) {
			const id = item.entity_index,
				index = item.baseline_index;
			if (
				!Number.isInteger(id) ||
				id! < 0 ||
				id! >= 16384 ||
				!Number.isInteger(index) ||
				index! < 0 ||
				index! >= 65536 ||
				overrides.has(id!)
			)
				throw new Error('Invalid alternate baseline');
			overrides.set(id!, index!);
		}
		this.waitingFull = false;
		this.pending = {
			tick,
			bank,
			update: msg.update_baseline === true,
			delta,
			members: previous?.members.slice() ?? new Uint32Array(512),
			dormant: previous?.dormant.slice() ?? new Uint32Array(512),
			outOfPvs: new Uint32Array(512),
			next: msg.update_baseline === true ? new Map(this.banks[bank]) : null,
			overrides
		};
		return true;
	}
	private transaction() {
		if (!this.pending) throw new Error('No entity packet');
		return this.pending;
	}
	private checkId(id: number) {
		if (!Number.isInteger(id) || id < 0 || id >= 16384) throw new Error('Invalid entity index');
	}
	baseline(id: number, classId: number) {
		this.checkId(id);
		const p = this.transaction();
		const base = p.delta ? this.banks[p.bank].get(id) : undefined;
		return base?.classId === classId ? structuredClone(base.properties) : undefined;
	}
	alternate(id: number) {
		this.checkId(id);
		return this.transaction().overrides.get(id);
	}
	enter(id: number, classId: number, properties: Record<string, unknown>) {
		this.checkId(id);
		const p = this.transaction();
		p.members[id >>> 5]! |= 1 << (id & 31);
		if (p.update) p.next!.set(id, { classId, properties: structuredClone(properties) });
	}
	update(id: number) {
		this.checkId(id);
		this.transaction().members[id >>> 5]! |= 1 << (id & 31);
	}
	leave(id: number) {
		this.checkId(id);
		this.transaction().members[id >>> 5]! &= ~(1 << (id & 31));
	}
	markOutOfPvs(id: number) {
		this.checkId(id);
		const p = this.transaction();
		p.outOfPvs[id >>> 5]! |= 1 << (id & 31);
		p.members[id >>> 5]! &= ~(1 << (id & 31));
	}
	markDormant(id: number, value: boolean) {
		this.checkId(id);
		const p = this.transaction();
		if (value) p.dormant[id >>> 5]! |= 1 << (id & 31);
		else p.dormant[id >>> 5]! &= ~(1 << (id & 31));
	}
	present(id: number) {
		this.checkId(id);
		const p = this.transaction();
		return Boolean((p.members[id >>> 5]! | p.dormant[id >>> 5]! | p.outOfPvs[id >>> 5]!) & (1 << (id & 31)));
	}
	finish(deltaFrom: number | undefined) {
		const p = this.transaction();
		if (p.update) this.banks[p.bank === 0 ? 1 : 0] = p.next!;
		this.frames.set(p.tick, { members: p.members, dormant: p.dormant });
		this.latest = p.tick;
		// Retain the source frame and newer frames, as the official snapshot list does.
		if (deltaFrom !== undefined)
			for (const tick of this.frames.keys()) if (tick < deltaFrom) this.frames.delete(tick);
		// Bounded receiver memory. A later reference outside this window requests a full update.
		while (this.frames.size > 128) this.frames.delete(this.frames.keys().next().value!);
		this.pending = null;
		return { tick: p.tick, baselineAck: p.update ? p.bank : null, full: !p.delta };
	}
	recover(minimumTick = 0) {
		this.reset();
		this.minimumFullTick = minimumTick;
		this.waitingFull = true;
	}
	reset() {
		this.waitingFull = false;
		this.minimumFullTick = 0;
		this.pending = null;
		this.banks = [new Map(), new Map()];
		this.frames.clear();
		this.latest = -1;
	}
}
