"""HL action signing — vendored minimal, PURE STDLIB (docs/HYPERLIQUID.md §6.1).

The deliberate dependency decision: no eth-account/coincurve/msgpack. Everything
a signed /exchange action needs is implemented here from primitives —
  keccak-256          (Ethereum's Keccak, NOT NIST SHA-3: 0x01 padding),
  msgpack             (the subset HL actions use, byte-identical to msgpack.packb),
  secp256k1 + RFC6979 (deterministic ECDSA, low-s, recovery id),
  EIP-712             (the fixed 'Agent' phantom payload HL signs)
— because the whole pipeline is pinned bit-for-bit against the official SDK's
production test vectors in tests/spec_hyperliquid_signing.py. Do not edit any
constant here without re-running that spec.

The action hash (mirrors the SDK exactly):
  keccak( msgpack(action) ++ nonce_u64_be ++ (0x00 | 0x01++vault20) [++ 0x00++expires_u64_be] )
then EIP-712-sign the phantom agent {source: 'a'|'b', connectionId: hash} under
domain Exchange/1/chainId 1337. The nonce is a ms timestamp, strictly increasing
per account (see exchange.py).

Cloid <-> link_id: HL's client order id is 16 bytes hex. Our link_ids
('perBTCl-5') are short ASCII, so they ride INSIDE the cloid verbatim,
null-padded — reversible (truth can read identity straight off the exchange,
same as Bybit's orderLinkId) and human-readable in a hex decoder. No hashing.
"""
import hashlib
import hmac

# ---------------------------------------------------------------- keccak-256
_KECCAK_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
# rotation offsets, indexed [x][y]
_KECCAK_ROT = (
    (0, 36, 3, 41, 18), (1, 44, 10, 45, 2), (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56), (27, 20, 39, 8, 14),
)
_M64 = (1 << 64) - 1


def _rotl(v, n):
    return ((v << n) | (v >> (64 - n))) & _M64


def _keccak_f(st):
    for rc in _KECCAK_RC:
        # theta
        c = [st[x] ^ st[x + 5] ^ st[x + 10] ^ st[x + 15] ^ st[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for i in range(25):
            st[i] ^= d[i % 5]
        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(st[x + 5 * y], _KECCAK_ROT[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                st[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y] & _M64)
        # iota
        st[0] ^= rc
    return st


def keccak256(data):
    rate = 136                                     # 1600 - 2*256 bits, in bytes
    buf = bytearray(data)
    buf.append(0x01)                               # Keccak pad10*1 domain (SHA-3 uses 0x06)
    while len(buf) % rate:
        buf.append(0)
    buf[-1] |= 0x80
    st = [0] * 25
    for off in range(0, len(buf), rate):
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(buf[off + 8 * i: off + 8 * i + 8], 'little')
        _keccak_f(st)
    return b''.join(st[i].to_bytes(8, 'little') for i in range(4))


# ---------------------------------------------------------------- msgpack (subset)
def msgpack_pack(obj):
    """The subset HL actions use, byte-identical to msgpack.packb(obj). Floats are
    REFUSED on purpose: every number on the HL wire is a string (float_to_wire) or
    an int — a float reaching here is a bug upstream, not something to encode."""
    out = bytearray()
    _pack(obj, out)
    return bytes(out)


def _pack(o, out):
    if o is None:
        out.append(0xC0)
    elif o is True:
        out.append(0xC3)
    elif o is False:
        out.append(0xC2)
    elif isinstance(o, int):
        _pack_int(o, out)
    elif isinstance(o, str):
        b = o.encode('utf-8')
        n = len(b)
        if n < 32:
            out.append(0xA0 | n)
        elif n < 256:
            out += b'\xd9' + bytes([n])
        elif n < 65536:
            out += b'\xda' + n.to_bytes(2, 'big')
        else:
            out += b'\xdb' + n.to_bytes(4, 'big')
        out += b
    elif isinstance(o, (bytes, bytearray)):
        n = len(o)
        if n < 256:
            out += b'\xc4' + bytes([n])
        elif n < 65536:
            out += b'\xc5' + n.to_bytes(2, 'big')
        else:
            out += b'\xc6' + n.to_bytes(4, 'big')
        out += bytes(o)
    elif isinstance(o, (list, tuple)):
        n = len(o)
        if n < 16:
            out.append(0x90 | n)
        elif n < 65536:
            out += b'\xdc' + n.to_bytes(2, 'big')
        else:
            out += b'\xdd' + n.to_bytes(4, 'big')
        for v in o:
            _pack(v, out)
    elif isinstance(o, dict):
        n = len(o)
        if n < 16:
            out.append(0x80 | n)
        elif n < 65536:
            out += b'\xde' + n.to_bytes(2, 'big')
        else:
            out += b'\xdf' + n.to_bytes(4, 'big')
        for k, v in o.items():                     # insertion order — the hash depends on it
            _pack(k, out)
            _pack(v, out)
    else:
        raise TypeError(f'msgpack: refusing type {type(o).__name__} '
                        f'(floats must be wire strings)')


def _pack_int(v, out):
    if v >= 0:
        if v < 0x80:
            out.append(v)
        elif v < 0x100:
            out += b'\xcc' + v.to_bytes(1, 'big')
        elif v < 0x10000:
            out += b'\xcd' + v.to_bytes(2, 'big')
        elif v < 0x100000000:
            out += b'\xce' + v.to_bytes(4, 'big')
        else:
            out += b'\xcf' + v.to_bytes(8, 'big')
    else:
        if v >= -32:
            out.append(v & 0xFF)
        elif v >= -0x80:
            out += b'\xd0' + v.to_bytes(1, 'big', signed=True)
        elif v >= -0x8000:
            out += b'\xd1' + v.to_bytes(2, 'big', signed=True)
        elif v >= -0x80000000:
            out += b'\xd2' + v.to_bytes(4, 'big', signed=True)
        else:
            out += b'\xd3' + v.to_bytes(8, 'big', signed=True)


# ---------------------------------------------------------------- secp256k1
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _jac_double(p):
    x, y, z = p
    if not y:
        return (0, 0, 0)
    ysq = y * y % _P
    s = 4 * x * ysq % _P
    m = 3 * x * x % _P                             # a = 0 on secp256k1
    nx = (m * m - 2 * s) % _P
    ny = (m * (s - nx) - 8 * ysq * ysq) % _P
    nz = 2 * y * z % _P
    return (nx, ny, nz)


def _jac_add(p, q):
    if not p[1]:
        return q
    if not q[1]:
        return p
    x1, y1, z1 = p
    x2, y2, z2 = q
    z1z1 = z1 * z1 % _P
    z2z2 = z2 * z2 % _P
    u1 = x1 * z2z2 % _P
    u2 = x2 * z1z1 % _P
    s1 = y1 * z2 * z2z2 % _P
    s2 = y2 * z1 * z1z1 % _P
    if u1 == u2:
        if s1 != s2:
            return (0, 0, 0)
        return _jac_double(p)
    h = u2 - u1
    r = s2 - s1
    h2 = h * h % _P
    h3 = h * h2 % _P
    u1h2 = u1 * h2 % _P
    nx = (r * r - h3 - 2 * u1h2) % _P
    ny = (r * (u1h2 - nx) - s1 * h3) % _P
    nz = h * z1 * z2 % _P
    return (nx, ny, nz)


def _point_mul(k, point=(_GX, _GY)):
    """k * point -> affine (x, y). Jacobian double-and-add; one inverse at the end."""
    acc = (0, 0, 0)
    add = (point[0], point[1], 1)
    while k:
        if k & 1:
            acc = _jac_add(acc, add)
        add = _jac_double(add)
        k >>= 1
    if not acc[2]:
        raise ValueError('point at infinity')
    zinv = pow(acc[2], _P - 2, _P)
    zinv2 = zinv * zinv % _P
    return (acc[0] * zinv2 % _P, acc[1] * zinv2 * zinv % _P)


def _rfc6979_k(priv, digest):
    """Deterministic nonce (RFC 6979, HMAC-SHA256) — the same k eth-account /
    libsecp256k1 derive, so signatures match the SDK's bit-for-bit."""
    x = priv.to_bytes(32, 'big')
    h1 = (int.from_bytes(digest, 'big') % _N).to_bytes(32, 'big')   # bits2octets
    v = b'\x01' * 32
    k = b'\x00' * 32
    k = hmac.new(k, v + b'\x00' + x + h1, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b'\x01' + x + h1, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, 'big')
        if 1 <= cand < _N:
            yield cand
        k = hmac.new(k, v + b'\x00', hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def ecdsa_sign(priv, digest):
    """Sign a 32-byte digest -> (r, s, v) with low-s and the Ethereum recovery id."""
    z = int.from_bytes(digest, 'big')
    for k in _rfc6979_k(priv, digest):
        px, py = _point_mul(k)
        r = px % _N
        if not r:
            continue
        s = pow(k, _N - 2, _N) * (z + r * priv) % _N
        if not s:
            continue
        recid = (py & 1) | (2 if px >= _N else 0)
        if s > _N // 2:                            # canonical low-s (EIP-2); flip parity
            s = _N - s
            recid ^= 1
        return r, s, 27 + recid


def priv_to_address(priv):
    """The wallet address of a private key — logged so a run SAYS which key signs."""
    x, y = _point_mul(_to_priv_int(priv))
    pub = x.to_bytes(32, 'big') + y.to_bytes(32, 'big')
    return '0x' + keccak256(pub)[12:].hex()


def _to_priv_int(key):
    if isinstance(key, int):
        priv = key
    else:
        priv = int(str(key).removeprefix('0x'), 16)
    if not 1 <= priv < _N:
        raise ValueError('private key out of range')
    return priv


# ---------------------------------------------------------------- EIP-712 / HL
def _u256(v):
    return v.to_bytes(32, 'big')


# domain Exchange/1/chainId 1337/contract 0x0 — constant for every L1 action
_DOMAIN_SEPARATOR = keccak256(
    keccak256(b'EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
    + keccak256(b'Exchange') + keccak256(b'1') + _u256(1337) + _u256(0))
_AGENT_TYPEHASH = keccak256(b'Agent(string source,bytes32 connectionId)')


def action_hash(action, vault_address, nonce, expires_after=None):
    """keccak(msgpack(action) ++ nonce ++ vault-flag [++ expires]) — the connectionId."""
    data = msgpack_pack(action) + int(nonce).to_bytes(8, 'big')
    if vault_address is None:
        data += b'\x00'
    else:
        data += b'\x01' + bytes.fromhex(vault_address.removeprefix('0x'))
    if expires_after is not None:
        data += b'\x00' + int(expires_after).to_bytes(8, 'big')
    return keccak256(data)


def sign_l1_action(private_key, action, vault_address, nonce, is_mainnet,
                   expires_after=None):
    """-> {'r': '0x..', 's': '0x..', 'v': 27|28}, exactly the SDK's output shape."""
    conn_id = action_hash(action, vault_address, nonce, expires_after)
    source = 'a' if is_mainnet else 'b'
    struct = keccak256(_AGENT_TYPEHASH + keccak256(source.encode()) + conn_id)
    digest = keccak256(b'\x19\x01' + _DOMAIN_SEPARATOR + struct)
    r, s, v = ecdsa_sign(_to_priv_int(private_key), digest)
    return {'r': hex(r), 's': hex(s), 'v': v}


# ---------------------------------------------------------------- cloid <-> link_id
CLOID_BYTES = 16


def link_to_cloid(link_id):
    """'perBTCl-5' -> '0x7065724254436c2d3500000000000000' — the link_id VERBATIM
    (ASCII, null-padded) so the exchange-side id is reversible and readable."""
    b = link_id.encode('ascii')
    if not b or len(b) > CLOID_BYTES:
        raise ValueError(f'link_id must be 1..{CLOID_BYTES} ASCII bytes, got {link_id!r}')
    return '0x' + b.ljust(CLOID_BYTES, b'\x00').hex()


def cloid_to_link(cloid):
    """Inverse of link_to_cloid. A cloid we didn't mint (not printable ASCII inside)
    returns None — the caller keeps the raw cloid, like a foreign Bybit link-id."""
    if not cloid or not cloid.startswith('0x') or len(cloid) != 2 + 2 * CLOID_BYTES:
        return None
    try:
        raw = bytes.fromhex(cloid[2:]).rstrip(b'\x00')
        s = raw.decode('ascii')
    except (ValueError, UnicodeDecodeError):
        return None
    return s if s and all(32 < ord(c) < 127 for c in s) else None
