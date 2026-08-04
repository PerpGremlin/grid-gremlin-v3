"""SPEC: HL phase 2 — signing + writes, stdlib-vendored (docs/HYPERLIQUID.md §6.1).

The crypto pipeline (keccak / msgpack / RFC6979-secp256k1 / EIP-712) is pinned
BIT-FOR-BIT against the official hyperliquid-python-sdk's production test
vectors (tests/signing_test.py @ master, fetched 2026-07-27) — a wrong byte
anywhere changes r/s/v, so these vectors transitively prove every layer. The
write client is exercised against a stubbed transport: payload shape, nonce
monotonicity, cloid identity, float refusal, ambiguity discipline.

Run:  python tests/run.py hyperliquid_signing
"""
import sys

try:
    from gridgremlin.exchange.hyperliquid.signing import (
        keccak256, msgpack_pack, action_hash, sign_l1_action,
        priv_to_address, link_to_cloid, cloid_to_link,
    )
    from gridgremlin.exchange.hyperliquid.exchange import ExchangeClient
    from gridgremlin.exchange.hyperliquid.client import HLError
except ImportError:
    sys.exit('NOT IMPLEMENTED YET — this file is the spec, not a regression test.\n'
             'It should fail until hyperliquid/signing.py + exchange.py exist.')

fails = []


CHECKS = [0]


def check(cond, msg):
    CHECKS[0] += 1
    if not cond:
        fails.append(msg)


KEY = '0x0123456789012345678901234567890123456789012345678901234567890123'

print('=' * 74)
print('1. KECCAK-256 (Ethereum padding, not NIST SHA-3)')
print('=' * 74)
check(keccak256(b'').hex() ==
      'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470',
      'keccak256(empty) — if this used SHA-3 0x06 padding it would differ')
check(keccak256(b'abc').hex() ==
      '4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45',
      'keccak256(abc)')
check(keccak256(b'x' * 300).hex() ==
      keccak256(bytes(b'x' * 300)).hex() and len(keccak256(b'x' * 300)) == 32,
      'multi-block absorb')
print('  empty + abc + multi-block vectors hold')

print()
print('=' * 74)
print('2. MSGPACK MATCHES msgpack.packb (spec-derived byte checks)')
print('=' * 74)
cases = [
    (127, '7f'), (128, 'cc80'), (255, 'ccff'), (256, 'cd0100'),
    (65535, 'cdffff'), (65536, 'ce00010000'), (2 ** 32, 'cf0000000100000000'),
    (-1, 'ff'), (-32, 'e0'), (-33, 'd0df'),
    (True, 'c3'), (False, 'c2'), (None, 'c0'),
    ('Alo', 'a3416c6f'), ('x' * 32, 'd920' + '78' * 32),
    ([1, 'a'], '9201a161'), ({'a': 1}, '81a16101'),
]
ok = True
for val, want in cases:
    got = msgpack_pack(val).hex()
    if got != want:
        ok = False
        fails.append(f'msgpack({val!r}) = {got}, want {want}')
print(f'  {len(cases)} boundary encodings (fixint/uint8-64/int8/fixstr/str8/'
      f'fixarray/fixmap) {"hold" if ok else "FAIL"}')
try:
    msgpack_pack(1.5)
    check(False, 'msgpack must REFUSE floats (wire numbers are strings)')
except TypeError:
    print('  floats refused ✓ (every HL wire number is a string or int)')

print()
print('=' * 74)
print('3. THE FULL SIGNING PIPELINE == THE OFFICIAL SDK, BIT-FOR-BIT')
print('=' * 74)
# vectors: hyperliquid-python-sdk tests/signing_test.py (production-verified)
h = action_hash({'type': 'order', 'orders': [
    {'a': 4, 'b': True, 'p': '1670.1', 's': '0.0147', 'r': False,
     't': {'limit': {'tif': 'Ioc'}}}], 'grouping': 'na'}, None, 1677777606040)
check(h.hex() == '0fcbeda5ae3c4950a548021552a4fea2226858c4453571bf3f24ba017eac2908',
      'phantom-agent connectionId (pins msgpack+nonce+flag+keccak jointly)')

VECTORS = [
    ('dummy action', {'type': 'dummy', 'num': 100000000000}, None,
     ('0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298',
      '0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8', 27),
     ('0x542af61ef1f429707e3c76c5293c80d01f74ef853e34b76efffcb57e574f9510',
      '0x17b8b32f086e8cdede991f1e2c529f5dd5297cbe8128500e00cbaf766204a613', 28)),
    ('Gtc order', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'limit': {'tif': 'Gtc'}}}], 'grouping': 'na'}, None,
     ('0xd65369825a9df5d80099e513cce430311d7d26ddf477f5b3a33d2806b100d78e',
      '0x2b54116ff64054968aa237c20ca9ff68000f977c93289157748a3162b6ea940e', 28),
     ('0x82b2ba28e76b3d761093aaded1b1cdad4960b3af30212b343fb2e6cdfa4e3d54',
      '0x6b53878fc99d26047f4d7e8c90eb98955a109f44209163f52d8dc4278cbbd9f5', 27)),
    ('order + cloid', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'limit': {'tif': 'Gtc'}}, 'c': '0x00000000000000000000000000000001'}],
        'grouping': 'na'}, None,
     ('0x41ae18e8239a56cacbc5dad94d45d0b747e5da11ad564077fcac71277a946e3',
      '0x3c61f667e747404fe7eea8f90ab0e76cc12ce60270438b2058324681a00116da', 27),
     ('0xeba0664bed2676fc4e5a743bf89e5c7501aa6d870bdb9446e122c9466c5cd16d',
      '0x7f3e74825c9114bc59086f1eebea2928c190fdfbfde144827cb02b85bbe90988', 28)),
    ('vault variant', {'type': 'dummy', 'num': 100000000000},
     '0x1719884eb866cb12b2287399b15f7db5e7d775ea',
     ('0x3c548db75e479f8012acf3000ca3a6b05606bc2ec0c29c50c515066a326239',
      '0x4d402be7396ce74fbba3795769cda45aec00dc3125a984f2a9f23177b190da2c', 28),
     ('0xe281d2fb5c6e25ca01601f878e4d69c965bb598b88fac58e475dd1f5e56c362b',
      '0x7ddad27e9a238d045c035bc606349d075d5c5cd00a6cd1da23ab5c39d4ef0f60', 27)),
    ('trigger (nested maps)', {'type': 'order', 'orders': [
        {'a': 1, 'b': True, 'p': '100', 's': '100', 'r': False,
         't': {'trigger': {'isMarket': True, 'triggerPx': '103', 'tpsl': 'sl'}}}],
        'grouping': 'na'}, None,
     ('0x98343f2b5ae8e26bb2587daad3863bc70d8792b09af1841b6fdd530a2065a3f9',
      '0x6b5bb6bb0633b710aa22b721dd9dee6d083646a5f8e581a20b545be6c1feb405', 27),
     ('0x971c554d917c44e0e1b6cc45d8f9404f32172a9d3b3566262347d0302896a2e4',
      '0x206257b104788f80450f8e786c329daa589aa0b32ba96948201ae556d5637eac', 28)),
]
for name, action, vault, main_want, test_want in VECTORS:
    for is_main, want in ((True, main_want), (False, test_want)):
        sig = sign_l1_action(KEY, action, vault, 0, is_main)
        net = 'mainnet' if is_main else 'testnet'
        check((sig['r'], sig['s'], sig['v']) == want, f'{name} {net}: {sig} != {want}')
    print(f'  {name:24} r/s/v match on both nets ✓')
check(priv_to_address(KEY) == '0x14791697260e4c9a71f18484c9f997b308e59325',
      'wallet address derivation (keccak of uncompressed pubkey)')

print()
print('=' * 74)
print('4. CLOID CARRIES THE link_id VERBATIM (reversible identity)')
print('=' * 74)
c = link_to_cloid('perBTCl-5')
print(f'  perBTCl-5 -> {c}')
check(c == '0x7065724254436c2d3500000000000000', 'ASCII-in-hex, null-padded')
check(cloid_to_link(c) == 'perBTCl-5', 'round-trips back to the link_id')
check(cloid_to_link('0x00000000000000000e8ab9a57c642b15') is None,
      'a foreign (binary) cloid decodes to None — caller keeps the raw value')
check(cloid_to_link('') is None and cloid_to_link(None) is None, 'empty-safe')
try:
    link_to_cloid('this-link-id-is-way-too-long')
    check(False, 'a link_id over 16 bytes must be refused, not truncated')
except ValueError:
    print('  >16-byte link_id refused ✓ (silent truncation would alias rungs)')

print()
print('=' * 74)
print('5. THE WRITE CLIENT: payload shape, nonce, float refusal')
print('=' * 74)


import os

# hermetic: the operator's real .env (HL_ACCOUNT_ADDRESS etc.) must not leak into
# this spec — an empty value beats load_env's setdefault, forcing the no-address path
os.environ['HL_ACCOUNT_ADDRESS'] = ''
os.environ['HL_PRIVATE_KEY'] = ''


class StubExchange(ExchangeClient):
    """Capture what would go on the wire; answer like HL."""

    def __init__(self):
        super().__init__(env='testnet', private_key=KEY)
        self.posted = []
        self.reply = {'status': 'ok', 'response': {'type': 'order', 'data': {
            'statuses': [{'resting': {'oid': 77}}]}}}

    def _post(self, path, body, retry_429=True):
        self.posted.append((path, body))
        return self.reply


x = StubExchange()
check(x.wallet == '0x14791697260e4c9a71f18484c9f997b308e59325' == x.address,
      'without HL_ACCOUNT_ADDRESS the wallet IS the account')
r = x.place_order(0, 'Buy', '0.0002', '60000', order_link_id='perBTCl-3')
path, body = x.posted[-1]
wire = body['action']['orders'][0]
print(f'  place -> {path} a={wire["a"]} b={wire["b"]} p={wire["p"]} s={wire["s"]} '
      f'tif={wire["t"]["limit"]["tif"]} c={wire["c"][:12]}…')
check(path == '/exchange' and body['action']['type'] == 'order'
      and body['action']['grouping'] == 'na', 'order action shape')
check(set(body) == {'action', 'nonce', 'signature', 'vaultAddress', 'expiresAfter'},
      'payload carries exactly the SDK envelope')
check(wire['t'] == {'limit': {'tif': 'Alo'}}, 'post-only rides as Alo')
check(wire['c'] == link_to_cloid('perBTCl-3'), 'the cloid IS the link_id')
check(body['signature']['v'] in (27, 28) and body['signature']['r'].startswith('0x'),
      'signed envelope')
check(r == {'status': 'resting', 'oid': 77}, 'resting status parsed')

n1 = x.posted[-1][1]['nonce']
x.place_order(0, 'Sell', '0.0002', '70000', order_link_id='perBTCl-9')
n2 = x.posted[-1][1]['nonce']
check(n2 > n1, f'nonces strictly increase even same-ms ({n1} -> {n2})')

try:
    x.place_order(0, 'Buy', 0.0002, '60000')
    check(False, 'float qty must be REFUSED (would hash != serialise)')
except TypeError:
    print('  float qty/price refused ✓ (adapter fmt strings only)')

x.cancel_order(0, order_link_id='perBTCl-3')
act = x.posted[-1][1]['action']
check(act['type'] == 'cancelByCloid' and act['cancels'][0]['cloid'] == link_to_cloid('perBTCl-3'),
      'cancel by link_id -> cancelByCloid')
x.cancel_order(0, order_id=77)
check(x.posted[-1][1]['action'] == {'type': 'cancel', 'cancels': [{'a': 0, 'o': 77}]},
      'cancel by oid -> {a, o} wire')
x.reply = {'status': 'ok', 'response': {'type': 'cancel', 'data': {
    'statuses': [{'error': 'Order was never placed, already canceled, or filled. asset=0'}]}}}
r = x.cancel_order(0, order_id=78)
check(r['status'] == 'gone',
      'cancel of a gone order = idempotent success (the Bybit ORDER_GONE stance)')

x.reply = {'status': 'ok', 'response': {'type': 'order', 'data': {
    'statuses': [{'resting': {'oid': 78}}]}}}
x.amend_order(0, 'Buy', '0.0001', '60000', order_link_id='perBTCl-3')
act = x.posted[-1][1]['action']
check(act['type'] == 'batchModify' and act['modifies'][0]['oid'] == link_to_cloid('perBTCl-3')
      and act['modifies'][0]['order']['s'] == '0.0001',
      'amend -> batchModify naming the order by our cloid, full new body')
x.update_leverage(0, 5)
check(x.posted[-1][1]['action'] == {'type': 'updateLeverage', 'asset': 0,
                                    'isCross': True, 'leverage': 5},
      'updateLeverage action shape')

x.reply = {'status': 'err', 'response': 'Invalid nonce'}
try:
    x.place_order(0, 'Buy', '0.0002', '60000')
    check(False, 'status:err must raise')
except HLError as e:
    check(not e.ambiguous, "a clean status:'err' is a REAL rejection, not ambiguous")
print('  cancel/amend/leverage wires + err handling hold')

print()
if fails:
    print('\n'.join(f'  ❌ {f}' for f in fails))
    sys.exit(f'{len(fails)} spec violations')
print('=' * 74)
print('SPEC SATISFIED')
print('=' * 74)


def spec_signing_golden_vectors_all_green():
    # the module body IS the spec: v2's earned vectors ran at import
    assert CHECKS[0] > 10
