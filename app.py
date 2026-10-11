#!/usr/bin/env python3
"""
FUZZY BOT ARENA : SWARM PROTOCOL  (v4.0 -- WAR MACHINE edition)
===============================================================
SIX fuzzy inference engines drive everything:
  1. Drone brains (GRUNT/RUSHER/SNIPER/PHANTOM/BOMBER)  -- Sugeno, 6 inputs
  2. WARDEN boss phase I & II                           -- true Mamdani (clip,
     max-union, centroid); phase II swaps in a second rule bank at 50% HP
  3. HOMING target scorer -- missiles & captured turrets rank every candidate
     with threat/dist/off-axis/target-hp memberships -> desirability
  4. FUZZY DIRECTOR -- dynamic difficulty from flow/hull/pressure

Also: 4 weapons with per-weapon upgrade pools, pilots, relics/curses with
synergy tags, chill (laggy 20Hz brains!) & burn statuses, laser sweepers,
crumbling tiles, capturable turrets, achievements, pilot unlocks, and a
flight recorder that graphs your best run from disk.

Controls: WASD move | mouse aim | click/SPACE shoot (PULSE: hold=charge) |
E/right-click dash | TAB drone | G director page | 1-4 pilot, 5-8 weapon |
ENTER launch | L meta | F panel | SHIFT slow-mo | -/= bias | C crt | M mute | P pause
"""

import sys, os, re, json, math, random, array
from collections import deque

try:
    import pygame
except ImportError:
    sys.exit("pygame is required:  pip install pygame")

# ------------------------------------------------------------------ config --
WIDTH, HEIGHT = 1240, 740
PLAY_W = 910
PANEL_X = WIDTH - 330
FPS = 60
TILE = 84

COL = dict(
    bg=(13, 16, 24), grid=(23, 29, 42), border=(58, 76, 105),
    panel=(15, 19, 28), edge=(52, 66, 92),
    text=(218, 226, 240), dim=(122, 136, 160),
    gold=(255, 206, 92), green=(118, 255, 142), red=(255, 92, 92),
    player=(96, 226, 255), pbullet=(150, 240, 255),
    purple=(196, 126, 255), ebullet=(255, 158, 82),
)
SET_COLORS = ((92, 216, 255), (255, 172, 72), (255, 106, 200), (132, 255, 142))
SYS_COL = {'approach': (120, 200, 255), 'strafe': (255, 190, 90), 'fire': (255, 120, 120)}
DIR_COL = {'spawn': (150, 255, 170), 'power': (255, 140, 140), 'care': (120, 200, 255)}

def _clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v
def dim(c, f): return (int(c[0] * f), int(c[1] * f), int(c[2] * f))
def lerp(a, b, t):
    t = _clamp(t, 0.0, 1.0)
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))
def lighten(c, f=0.5): return lerp(c, (255, 255, 255), f)

# ------------------------------------------------------------ meta progress -
META_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fuzzmeta.json')
BEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fuzzbest.txt')
META_DEFAULT = {'best': 0, 'ach': {},
                'totals': {'kills': 0, 'waves': 0, 'boss': 0, 'burn': 0,
                           'turret': 0, 'elites': 0, 'runs': 0, 'flawless': 0},
                'replay': None, 'last': None}

def load_meta():
    m = json.loads(json.dumps(META_DEFAULT))
    try:
        d = json.load(open(META_FILE))
        for k, v in d.items():
            if k == 'totals' and isinstance(v, dict): m['totals'].update(v)
            else: m[k] = v
    except Exception:
        try: m['best'] = int(open(BEST_FILE).read().strip())
        except Exception: pass
    return m

def save_meta(m):
    try: json.dump(m, open(META_FILE, 'w'))
    except Exception: pass

# key, name, description, predicate(meta, game-or-None)
ACH = [
 ('first',   'FIRST CONTACT',  'destroy a drone',          lambda m, g: m['totals']['kills'] >= 1),
 ('combo5',  'CHAIN REACTION', 'reach combo x5',           lambda m, g: g and g.stats['best_mult'] >= 5),
 ('wave10',  'DEEP RUN',       'reach wave 10',            lambda m, g: m['totals']['waves'] >= 10),
 ('boss',    'WARDEN DOWN',    'destroy a WARDEN',         lambda m, g: m['totals']['boss'] >= 1),
 ('flawless','UNTOUCHED',      'clear a wave undamaged',   lambda m, g: m['totals']['flawless'] >= 1),
 ('pyro',    'PYROMANIAC',     'burn 25 drones to death',  lambda m, g: m['totals']['burn'] >= 25),
 ('rich',    'HIGH ROLLER',    'score 12000 in one run',   lambda m, g: g and g.score >= 12000),
 ('cursed',  'MASOCHIST',      'hold 2 relics at once',    lambda m, g: g and len(g.relics) >= 2),
 ('sky',     'FRIENDLY SKIES', 'capture 3 turret nodes',   lambda m, g: m['totals']['turret'] >= 3),
]

def pilot_ok(m, k):
    if k == 'NOVA':    return 'combo5' in m['ach']
    if k == 'BULWARK': return m['totals']['waves'] >= 8
    if k == 'GHOST':   return m['totals']['burn'] >= 25
    return True

PILOTS = {
 'ACE':     dict(col=(96, 226, 255),  blurb='balanced operative'),
 'NOVA':    dict(col=(255, 206, 92),  blurb='hyper capacitor, -20 hull'),
 'BULWARK': dict(col=(118, 255, 142), blurb='+40 hull, 1 shield, -12% speed'),
 'GHOST':   dict(col=(196, 126, 255), blurb='drones see you 50%, -15% score'),
}
PILOT_ORDER = ['ACE', 'NOVA', 'BULWARK', 'GHOST']
WEAPON_ORDER = ['PULSE', 'RAIL', 'FLAK', 'HOMING']

WEAPONS = {
 'PULSE': dict(name='PULSE RIFLE', tag='fire', col=COL['pbullet'], sfx='shoot',
               blurb=('reliable full-auto', 'hold fire to charge a bolt'),
               rate=0.19, dmg=26, spd=560, pellets=1, spread=0.0, r=3.5,
               pierce=0, life=1.8, knock=0.05),
 'RAIL':  dict(name='RAILGUN', tag='rail', col=(255, 250, 190), sfx='rail',
               blurb=('slow bolt, pierces everything', 'massive knockback'),
               rate=0.62, dmg=88, spd=1000, pellets=1, spread=0.0, r=4.5,
               pierce=3, life=1.6, knock=0.16),
 'FLAK':  dict(name='FLAK CANNON', tag='flak', col=(255, 200, 120), sfx='flak',
               blurb=('6-pellet close-range burst', 'stack pellets via tags'),
               rate=0.55, dmg=12, spd=660, pellets=6, spread=0.40, r=3.0,
               pierce=0, life=0.40, knock=0.03),
 'HOMING': dict(name='SWARM PODS', tag='homing', col=(180, 255, 160), sfx='missile',
               blurb=('missiles pick targets with', 'a fuzzy scorer - watch TAB')),
               rate=0.52, dmg=30, spd=340, pellets=2, spread=0.5, r=4.0,
               pierce=0, life=4.0, knock=0.05, splash=55),
}

# ============================================================ fuzzy library =
class MF:
    def __init__(self, corners): self.corners = corners
    def __call__(self, x): raise NotImplementedError

class TriMF(MF):
    def __init__(self, a, b, c):
        super().__init__([(a, 0), (b, 1), (c, 0)])
        self.a, self.b, self.c = a, b, c
    def __call__(self, x):
        a, b, c = self.a, self.b, self.c
        if x <= a or x >= c: return 0.0
        if x == b: return 1.0
        return (x - a) / (b - a) if x < b else (c - x) / (c - b)

class TrapMF(MF):
    def __init__(self, a, b, c, d):
        super().__init__([(a, 0), (b, 1), (c, 1), (d, 0)])
        self.a, self.b, self.c, self.d = a, b, c, d
    def __call__(self, x):
        a, b, c, d = self.a, self.b, self.c, self.d
        if b <= x <= c: return 1.0
        if x <= a or x >= d: return 0.0
        return (x - a) / (b - a) if x < b else (d - x) / (d - c)

class FuzzyVar:
    def __init__(self, name, lo, hi):
        self.name, self.lo, self.hi = name, lo, hi
        self.sets = []
    def add(self, sname, mf):
        self.sets.append((sname, mf)); return self
    def fuzzify(self, x):
        x = _clamp(x, self.lo, self.hi)
        return {s: mf(x) for s, mf in self.sets}

class Rule:
    __slots__ = ('ants', 'z', 'label')
    def __init__(self, ants, z, label=''):
        self.ants, self.z, self.label = ants, z, label
    def strength(self, fz):
        s = 1.0
        for vn, sn in self.ants:
            s = min(s, fz.get(vn, {}).get(sn, 0.0))
            if s <= 0: return 0.0
        return s

class FuzzySystem:
    """Zero-order Sugeno: min-AND, crisp z per rule, weighted-average output."""
    def __init__(self, name):
        self.name, self.vars, self.rules = name, {}, []
    def add_var(self, var): self.vars[var.name] = var
    def add_rule(self, ants, z, label): self.rules.append(Rule(ants, z, label))
    def evaluate(self, values):
        fz = {n: v.fuzzify(values.get(n, (v.lo + v.hi) / 2)) for n, v in self.vars.items()}
        num = den = 0.0; acts = []
        for r in self.rules:
            s = r.strength(fz); acts.append((r, s))
            if s > 0: num += s * r.z; den += s
        return (num / den if den > 1e-9 else 0.0), fz, acts

class MamdaniSystem:
    """Classic Mamdani: clip output sets at rule strength, max-union, centroid."""
    def __init__(self, name, ovar, N=81):
        self.name, self.ovar, self.N = name, ovar, N
        self.vars, self.rules = {}, []
        lo, hi = ovar.lo, ovar.hi
        self.xs = [lo + (hi - lo) * i / (N - 1) for i in range(N)]
        self.out_names = [n for n, _ in ovar.sets]
        self.out_mus = [[mf(x) for x in self.xs] for _, mf in ovar.sets]
    def add_var(self, var): self.vars[var.name] = var
    def add_rule(self, ants, target, label): self.rules.append(Rule(ants, target, label))
    def evaluate(self, values):
        fz = {n: v.fuzzify(values.get(n, (v.lo + v.hi) / 2)) for n, v in self.vars.items()}
        agg = [0.0] * self.N; acts = []
        for r in self.rules:
            s = r.strength(fz); acts.append((r, s))
            if s <= 0: continue
            mus = self.out_mus[self.out_names.index(r.z)]
            for i, m in enumerate(mus):
                v = m if m < s else s
                if v > agg[i]: agg[i] = v
        den = sum(agg)
        c = sum(x * m for x, m in zip(self.xs, agg)) / den if den > 1e-9 else 0.0
        return c, fz, acts, list(zip(self.xs, agg))

# ------------------------------------------------------------ drone inputs --
def make_vars():
    dist = FuzzyVar('dist', 0, 900)
    dist.add('NEAR', TrapMF(0, 0, 90, 230)).add('MID', TriMF(150, 340, 560)) \
        .add('FAR', TrapMF(450, 650, 900, 900))
    hp = FuzzyVar('health', 0, 320)
    hp.add('LOW', TrapMF(0, 0, 40, 90)).add('MID', TriMF(70, 160, 250)) \
      .add('HIGH', TrapMF(200, 260, 320, 320))
    dang = FuzzyVar('danger', 0, 1)
    dang.add('SAFE', TrapMF(0, 0, 0.12, 0.38)).add('THREAT', TrapMF(0.22, 0.55, 1, 1))
    watch = FuzzyVar('watch', 0, 1)
    watch.add('UNSEEN', TrapMF(0, 0, 0.15, 0.45)).add('WATCHED', TrapMF(0.30, 0.60, 1, 1))
    pack = FuzzyVar('pack', 0, 1)
    pack.add('LONE', TrapMF(0, 0, 0.10, 0.40)).add('PACKED', TrapMF(0.25, 0.55, 1, 1))
    prey = FuzzyVar('prey', 0, 140)
    prey.add('WEAK', TrapMF(0, 0, 40, 70)).add('STRONG', TrapMF(70, 95, 140, 140))
    return (dist, hp, dang, watch, pack, prey)

VARS = make_vars()

# ------------------------------------------------------ personality brains --
BOSS_OVAR = FuzzyVar('approach_out', -1, 1)
BOSS_OVAR.add('RETREAT', TriMF(-1.15, -0.85, -0.15)).add('HOLD', TriMF(-0.4, 0, 0.4)) \
         .add('ADVANCE', TriMF(0.15, 0.85, 1.15))

RULES = {
 'GRUNT': dict(
   approach=[([('dist', 'FAR')], 0.90, 'far -> advance'),
             ([('dist', 'MID')], 0.35, 'mid -> drift in'),
             ([('dist', 'NEAR')], -0.10, 'near -> hold range'),
             ([('dist', 'NEAR'), ('health', 'LOW')], -0.95, 'near+hurt -> FLEE'),
             ([('dist', 'MID'), ('health', 'LOW')], -0.35, 'mid+hurt -> back off')],
   strafe=[([('danger', 'THREAT')], 0.95, 'under fire -> juke'),
           ([('watch', 'WATCHED')], 0.55, 'aimed at -> sidestep'),
           ([('dist', 'NEAR'), ('health', 'HIGH')], 0.55, 'strong+close -> circle'),
           ([('pack', 'PACKED')], 0.30, 'crowded -> spread out')],
   fire=[([('dist', 'NEAR')], 0.95, 'near -> spray'),
         ([('dist', 'MID'), ('health', 'HIGH')], 0.70, 'mid+healthy -> shoot'),
         ([('danger', 'THREAT')], 0.55, 'dodging -> return fire'),
         ([('dist', 'FAR')], 0.20, 'far -> pot shots'),
         ([('health', 'LOW')], 0.35, 'hurt -> covering fire')]),
 'RUSHER': dict(
   approach=[([('dist', 'FAR')], 1.00, 'far -> CHARGE'),
             ([('dist', 'MID')], 0.85, 'mid -> charge'),
             ([('dist', 'NEAR')], 0.45, 'near -> RAM'),
             ([('dist', 'NEAR'), ('health', 'LOW')], 0.95, 'near+hurt -> BERSERK'),
             ([('dist', 'MID'), ('health', 'LOW')], 0.70, 'wounded fury')],
   strafe=[([('danger', 'THREAT')], 0.90, 'under fire -> juke'),
           ([('pack', 'PACKED')], 0.40, 'crowded -> spread')],
   fire=[([('dist', 'NEAR')], 0.95, 'point blank -> spray'),
         ([('dist', 'MID')], 0.45, 'mid -> wild fire'),
         ([('dist', 'FAR')], 0.10, 'far -> hold')]),
 'SNIPER': dict(
   approach=[([('dist', 'FAR')], 0.40, 'far -> keep range'),
             ([('dist', 'MID')], 0.10, 'mid -> drift'),
             ([('dist', 'NEAR')], -0.90, 'too close -> RETREAT'),
             ([('dist', 'NEAR'), ('health', 'HIGH')], -0.55, 'near -> back off')],
   strafe=[([('watch', 'WATCHED')], 0.95, 'in crosshair -> DODGE'),
           ([('danger', 'THREAT')], 0.85, 'under fire -> juke'),
           ([('dist', 'FAR')], 0.20, 'far -> steady')],
   fire=[([('dist', 'FAR')], 0.95, 'long shot'),
         ([('dist', 'FAR'), ('watch', 'UNSEEN')], 0.80, 'unseen -> take the shot'),
         ([('dist', 'MID')], 0.60, 'mid -> aimed shot'),
         ([('dist', 'NEAR')], 0.25, 'panicked shot')]),
 'PHANTOM': dict(
   approach=[([('prey', 'WEAK')], 0.70, 'prey is hurt -> close in'),
             ([('watch', 'UNSEEN')], 0.60, 'unseen -> stalk'),
             ([('watch', 'WATCHED'), ('dist', 'NEAR')], -0.85, 'seen up close -> vanish'),
             ([('prey', 'STRONG')], -0.40, 'healthy player -> keep away'),
             ([('dist', 'MID')], 0.05, 'hover')],
   strafe=[([('watch', 'WATCHED')], 0.90, 'watched -> weave'),
           ([('danger', 'THREAT')], 0.80, 'under fire -> juke')],
   fire=[([('watch', 'UNSEEN')], 0.60, 'from the dark'),
         ([('dist', 'MID')], 0.50, 'mid -> pot shot'),
         ([('dist', 'FAR')], 0.40, 'far -> pot shot'),
         ([('dist', 'NEAR'), ('watch', 'WATCHED')], 0.15, 'exposed -> hold')]),
 'BOMBER': dict(
   approach=[([('dist', 'FAR')], 0.95, 'long approach'),
             ([('dist', 'MID')], 0.78, 'close in'),
             ([('dist', 'NEAR')], 0.60, 'arming run'),
             ([('dist', 'NEAR'), ('health', 'LOW')], 0.85, 'primed - commit'),
             ([('danger', 'THREAT')], 0.30, 'weather the fire - steady')],
   strafe=[([('pack', 'PACKED')], 0.50, 'avoid clumping'),
           ([('danger', 'THREAT')], 0.25, 'slight weave')],
   fire=[([('dist', 'NEAR')], 0.05, 'no gun - just boom')]),
}

# WARDEN phase I / phase II Mamdani banks
BOSS_MAM_P1 = [
 ([('dist', 'FAR'), ('health', 'HIGH')], 'ADVANCE', 'far+strong -> ADVANCE'),
 ([('prey', 'WEAK')],                    'ADVANCE', 'prey weak -> ADVANCE'),
 ([('dist', 'MID')],                     'HOLD',    'mid -> HOLD'),
 ([('dist', 'NEAR')],                    'HOLD',    'near -> HOLD'),
 ([('dist', 'NEAR'), ('health', 'LOW')], 'RETREAT', 'near+hurt -> RETREAT'),
 ([('dist', 'FAR'), ('health', 'LOW')],  'HOLD',    'far+hurt -> regroup'),
]
BOSS_MAM_P2 = [
 ([('dist', 'FAR')],                                    'ADVANCE', 'p2: hunt it down'),
 ([('prey', 'WEAK')],                                   'ADVANCE', 'p2: blood scent'),
 ([('dist', 'MID')],                                    'ADVANCE', 'p2: press hard'),
 ([('dist', 'NEAR'), ('health', 'HIGH')],               'ADVANCE', 'p2: trample'),
 ([('dist', 'NEAR')],                                   'HOLD',    'p2: hold the edge'),
 ([('health', 'LOW')],                                  'RETREAT', 'p2: fallback only'),
]
BOSS_SUG_P1 = dict(
   strafe=[([('danger', 'THREAT')], 0.50, 'under fire -> shift'),
           ([('watch', 'WATCHED')], 0.40, 'aimed at -> shift')],
   fire=[([('dist', 'NEAR')], 0.90, 'near -> fan shot'),
         ([('dist', 'MID')], 0.80, 'mid -> fan shot'),
         ([('dist', 'FAR')], 0.30, 'far -> sparse'),
         ([('danger', 'THREAT')], 0.50, 'under fire -> barrage')])
BOSS_SUG_P2 = dict(
   strafe=[([('danger', 'THREAT')], 0.75, 'p2: violent weave'),
           ([('watch', 'WATCHED')], 0.65, 'p2: anti-aim shift')],
   fire=[([('dist', 'NEAR')], 1.00, 'p2: close fan'),
         ([('dist', 'MID')], 0.95, 'p2: mid fan'),
         ([('dist', 'FAR')], 0.55, 'p2: long fan'),
         ([('danger', 'THREAT')], 0.80, 'p2: barrage')])

class Brain:
    def __init__(self, kind):
        self.kind = kind; self.systems = {}; self.mam = None
        if kind in ('WARDEN', 'WARDEN_P2'):
            bank = BOSS_MAM_P1 if kind == 'WARDEN' else BOSS_MAM_P2
            sug = BOSS_SUG_P1 if kind == 'WARDEN' else BOSS_SUG_P2
            m = MamdaniSystem('approach', BOSS_OVAR)
            for v in VARS: m.add_var(v)
            for ants, tgt, lab in bank: m.add_rule(ants, tgt, lab)
            self.mam = m
            tbl = dict(approach=[], **sug)
        else:
            tbl = RULES[kind]
        for name in ('approach', 'strafe', 'fire'):
            if name in tbl and tbl[name]:
                s = FuzzySystem(name)
                for v in VARS: s.add_var(v)
                for ants, z, lab in tbl[name]: s.add_rule(ants, z, lab)
                self.systems[name] = s
    def think(self, vals):
        out, acts, fz, mags = {}, {}, None, None
        for name in ('approach', 'strafe', 'fire'):
            if name == 'approach' and self.mam is not None:
                c, f, a, pts = self.mam.evaluate(vals)
                out[name], acts[name] = c, a
                if fz is None: fz = f
                mags = (pts, self.mam.ovar, c)
            else:
                o, f, a = self.systems[name].evaluate(vals)
                out[name], acts[name] = o, a
                if fz is None: fz = f
        return out, fz, acts, mags

_BRAINS = {}
def get_brain(kind):
    if kind not in _BRAINS: _BRAINS[kind] = Brain(kind)
    return _BRAINS[kind]

# ======================================== HOMING / TURRET target scorer =====
# "which target do I want?" -- a perfect little fuzzy system.
_HD = FuzzyVar('dist', 0, 900)
_HD.add('NEAR', TrapMF(0, 0, 120, 300)).add('MID', TriMF(200, 420, 700)) \
   .add('FAR', TrapMF(500, 700, 900, 900))
_HT = FuzzyVar('threat', 0, 1)
_HT.add('LOW', TrapMF(0, 0, 0.25, 0.50)).add('HIGH', TrapMF(0.35, 0.65, 1, 1))
_HO = FuzzyVar('off', 0, 1)
_HO.add('TIGHT', TrapMF(0, 0, 0.18, 0.45)).add('WIDE', TrapMF(0.30, 0.60, 1, 1))
_HH = FuzzyVar('hp', 0, 320)
_HH.add('LOW', TrapMF(0, 0, 50, 110)).add('HIGH', TrapMF(130, 210, 320, 320))
HOMING_SYS = FuzzySystem('target_score')
for _v in (_HD, _HT, _HO, _HH): HOMING_SYS.add_var(_v)
for _a, _z, _l in [
 ([('threat', 'HIGH')], 0.85, 'high threat -> priority'),
 ([('hp', 'LOW')], 0.65, 'wounded -> finish it'),
 ([('off', 'TIGHT')], 0.45, 'on my nose -> easy'),
 ([('dist', 'NEAR')], 0.35, 'near -> take it'),
 ([('dist', 'FAR'), ('off', 'WIDE')], -0.35, 'far+wide -> skip'),
 ([('threat', 'LOW'), ('dist', 'FAR')], 0.05, 'boring -> ignore')]:
    HOMING_SYS.add_rule(_a, _z, _l)

def target_score(e, pos, heading=None):
    """Fuzzy desirability of enemy e seen from pos (heading = radians or None)."""
    d = e.pos.distance_to(pos)
    if heading is None:
        off = 0.0
    else:
        a = math.atan2(e.pos.y - pos.y, e.pos.x - pos.x)
        diff = abs((a - heading + math.pi) % (2 * math.pi) - math.pi)
        off = min(1.0, diff / math.pi)
    if e.kind == 'WARDEN': th = 1.0
    elif e.kind == 'BOMBER': th = 0.9 if e.fuse >= 0 else 0.6
    elif e.kind == 'SNIPER': th = 0.65
    else: th = 0.30
    out, fz, acts = HOMING_SYS.evaluate(
        {'dist': d, 'threat': th, 'off': off, 'hp': e.hp})
    return out, fz, acts

# ================================================ FUZZY DIRECTOR (meta AI) ==
def make_dir_vars():
    flow = FuzzyVar('flow', 0, 1)
    flow.add('RUST', TrapMF(0, 0, 0.22, 0.50)).add('STEADY', TriMF(0.35, 0.55, 0.75)) \
        .add('HOT', TrapMF(0.62, 0.82, 1, 1))
    hull = FuzzyVar('hull', 0, 140)
    hull.add('CRITICAL', TrapMF(0, 0, 25, 48)).add('HURT', TriMF(30, 62, 95)) \
        .add('HEALTHY', TrapMF(85, 115, 140, 140))
    press = FuzzyVar('pressure', 0, 1)
    press.add('CALM', TrapMF(0, 0, 0.14, 0.38)).add('HOT', TrapMF(0.28, 0.58, 1, 1))
    return (flow, hull, press)

DIR_VARS = make_dir_vars()
DIR_RULES = {
 'spawn': [([('flow', 'HOT'), ('hull', 'HEALTHY')], 1.00, 'hot streak -> crank spawns'),
           ([('flow', 'STEADY'), ('hull', 'HEALTHY')], 0.62, 'healthy -> push a little'),
           ([('flow', 'RUST')], 0.12, 'rusty -> ease off'),
           ([('hull', 'HURT'), ('flow', 'RUST')], 0.05, 'struggling -> breathe'),
           ([('hull', 'CRITICAL')], 0.05, 'player critical -> calm arena'),
           ([('pressure', 'HOT')], 0.08, 'too hot -> thin the swarm')],
 'power': [([('flow', 'HOT'), ('pressure', 'CALM')], 1.00, 'dominating -> faster drones'),
           ([('hull', 'HEALTHY'), ('flow', 'STEADY')], 0.55, 'steady -> mild push'),
           ([('flow', 'RUST')], 0.05, 'rusty -> slower drones'),
           ([('pressure', 'HOT')], 0.10, 'under pressure -> slow down')],
 'care':  [([('hull', 'CRITICAL')], 1.00, 'critical -> drop meds'),
           ([('hull', 'HURT')], 0.60, 'hurt -> be generous'),
           ([('flow', 'HOT')], 0.15, 'dominating -> tighten loot')],
}
DIR_SYS = {}
for _n, _rs in DIR_RULES.items():
    _s = FuzzySystem('director/' + _n)
    for _v in DIR_VARS: _s.add_var(_v)
    for _a, _z, _l in _rs: _s.add_rule(_a, _z, _l)
    DIR_SYS[_n] = _s

# ------------------------------------------------------------- enemy types --
TYPES = {
 'GRUNT':   dict(col=(196, 126, 255), speed=1.00, hp=1.00, bdmg=10, cdmg=10,
                 bspeed=1.00, rof=1.00, score=100,  frange=650, R=14),
 'RUSHER':  dict(col=(255, 120,  80), speed=1.40, hp=0.65, bdmg=9,  cdmg=18,
                 bspeed=0.95, rof=0.80, score=150,  frange=520, R=13),
 'SNIPER':  dict(col=(120, 230, 255), speed=0.85, hp=0.80, bdmg=16, cdmg=10,
                 bspeed=1.60, rof=0.55, score=170,  frange=980, R=14),
 'PHANTOM': dict(col=(150, 255, 170), speed=1.25, hp=0.55, bdmg=7,  cdmg=8,
                 bspeed=1.05, rof=0.90, score=190,  frange=700, R=13),
 'BOMBER':  dict(col=(255, 196,  64), speed=0.72, hp=0.90, bdmg=6,  cdmg=0,
                 bspeed=1.00, rof=1.00, score=170,  frange=400, R=16),
 'WARDEN':  dict(col=(255,  96, 200), speed=0.55, hp=1.00, bdmg=14, cdmg=25,
                 bspeed=1.05, rof=0.70, score=1500, frange=760, R=30, boss=True),
}

# ======================================================= 8-BIT AUDIO ENGINE =
SR = 22050
_MIX_CH = 1
_NOTE_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_NOTE_RX = re.compile(r'^([A-G])([#b]?)(\d)$')

def nfreq(tok):
    m = _NOTE_RX.match(tok)
    if not m: return 0.0
    semi = _NOTE_SEMI[m.group(1)] + (1 if m.group(2) == '#' else
                                     -1 if m.group(2) == 'b' else 0)
    return 440.0 * 2.0 ** ((semi + (int(m.group(3)) + 1) * 12 - 69) / 12.0)

def _newbuf(sec): return [0.0] * int(SR * sec)

def _env(n, pts):
    if n <= 1: return [0.0] * max(0, n)
    e = [0.0] * n
    seg = 0
    for i in range(n):
        t = i / (n - 1)
        while seg < len(pts) - 2 and t > pts[seg + 1][0]:
            seg += 1
        (t0, v0), (t1, v1) = pts[seg], pts[seg + 1]
        f = 0.0 if t1 <= t0 else _clamp((t - t0) / (t1 - t0), 0, 1)
        e[i] = v0 + (v1 - v0) * f
    return e

ENV_PLUCK = [(0, 0), (0.04, 1.0), (0.40, 0.45), (1.0, 0.0)]
ENV_HOLD  = [(0, 0), (0.05, 1.0), (0.82, 0.85), (1.0, 0.0)]
ENV_FADE  = [(0, 1.0), (1.0, 0.0)]
ENV_HAT   = [(0, 1.0), (0.25, 0.40), (1.0, 0.0)]
ENV_RISE  = [(0, 0.0), (1.0, 1.0)]

def v_pulse(buf, start, n, f0, f1=None, vol=0.25, duty=0.5, env=None,
            vib=0.0, vibhz=6.0):
    if f1 is None: f1 = f0
    n = max(0, min(n, len(buf) - start))
    if n <= 0: return
    if env is None: env = _env(n, ENV_HOLD)
    ph = 0.0
    tp = 2 * math.pi * vibhz / SR
    for i in range(n):
        f = f0 + (f1 - f0) * (i / n)
        if vib: f *= 1.0 + vib * math.sin(tp * i)
        ph += f / SR
        while ph >= 1.0: ph -= 1.0
        buf[start + i] += (1.0 if ph < duty else -1.0) * vol * env[i]

def v_tri(buf, start, n, f0, f1=None, vol=0.3, env=None):
    if f1 is None: f1 = f0
    n = max(0, min(n, len(buf) - start))
    if n <= 0: return
    if env is None: env = _env(n, ENV_HOLD)
    ph = 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * (i / n)
        ph += f / SR
        while ph >= 1.0: ph -= 1.0
        x = int(ph * 32) & 31
        q = (15 - x) if x < 16 else (x - 16)
        buf[start + i] += (q * 2.0 / 15.0 - 1.0) * vol * env[i]

def v_noise(buf, start, n, vol=0.25, div=1, env=None, seed=0x7FFF):
    n = max(0, min(n, len(buf) - start))
    if n <= 0: return
    if env is None: env = _env(n, ENV_FADE)
    reg = seed; cnt = 0; bit = 1
    for i in range(n):
        cnt -= 1
        if cnt <= 0:
            reg = (reg >> 1) | (((reg ^ (reg >> 14)) & 1) << 14)
            bit = reg & 1
            cnt = div
        buf[start + i] += (1.0 if bit else -1.0) * vol * env[i]

def d_kick(buf, at, vol=1.0):
    n = int(0.15 * SR)
    v_tri(buf, at, n, 165, 40, 0.85 * vol, _env(n, ENV_FADE))
    n2 = int(0.028 * SR)
    v_pulse(buf, at, n2, 100, 55, 0.5 * vol, 0.5, _env(n2, ENV_FADE))

def d_snare(buf, at, vol=1.0):
    n = int(0.13 * SR)
    v_noise(buf, at, n, 0.60 * vol, 2, _env(n, ENV_FADE))
    n2 = int(0.05 * SR)
    v_pulse(buf, at, n2, 220, 150, 0.4 * vol, 0.5, _env(n2, ENV_FADE))

def d_hat(buf, at, vol=0.25):
    n = int(0.035 * SR)
    v_noise(buf, at, n, vol, 1, _env(n, ENV_HAT))

def _mix(buf, vol=1.0, crush=5):
    peak = 1e-9
    for v in buf:
        a = v if v >= 0 else -v
        if a > peak: peak = a
    g = vol / peak
    lv = (1 << crush) - 1
    N = len(buf)
    fi = max(1, int(0.003 * SR)); fo = max(1, int(0.03 * SR))
    frames = array.array('h')
    ap = frames.append
    for i, v in enumerate(buf):
        if i < fi: v *= i / fi
        if i > N - fo: v *= max(0.0, (N - i) / fo)
        s = int(round(_clamp(v * g, -1.0, 1.0) * lv) / lv * 30000)
        ap(s)
        if _MIX_CH == 2: ap(s)
    try: return pygame.mixer.Sound(buffer=frames.tobytes())
    except Exception: return None

def _play_pattern(buf, pat, step, note_fn, gate=0.92):
    toks = pat.split()
    for i, tok in enumerate(toks):
        if tok in ('.', '-'): continue
        dur = 1
        while i + dur < len(toks) and toks[i + dur] == '-':
            dur += 1
        f = nfreq(tok)
        if f > 0:
            note_fn(buf, int(i * step * SR), int(step * dur * gate * SR), f)

def PI(duty, vol, env=ENV_HOLD, vib=0.0):
    def fn(buf, at, n, f):
        v_pulse(buf, at, n, f, f, vol, duty, _env(n, env), vib)
    return fn

def TI(vol, env=ENV_HOLD):
    def fn(buf, at, n, f):
        v_tri(buf, at, n, f, f, vol, _env(n, env))
    return fn

def _drums(buf, bars, step, style, hatvol=0.22):
    for b in range(bars):
        t0 = int(b * 16 * step * SR); st = int(step * SR)
        fill = (b % 4 == 3)
        if style == 'rock':
            for s in (0, 8) + ((10, 14) if fill else ()):
                d_kick(buf, t0 + s * st)
            for s in (4, 12): d_snare(buf, t0 + s * st)
            for s in range(0, 16, 2):
                d_hat(buf, t0 + s * st, hatvol if s % 4 == 0 else hatvol * 0.55)
        else:
            for s in (0, 4, 8, 12) + ((14,) if fill else ()):
                d_kick(buf, t0 + s * st)
            for s in (4, 12): d_snare(buf, t0 + s * st)
            for s in range(16):
                d_hat(buf, t0 + s * st, hatvol if s % 4 == 2 else hatvol * 0.45)

def _build_tracks():
    tracks = {}
    step = 60 / 132 / 4; bars = 8
    buf = _newbuf(step * 16 * bars + 0.05)
    roots = ['A2', 'F2', 'C3', 'G2'] * 2
    fifths = ['E3', 'C3', 'G2', 'D3'] * 2
    bass = []
    for r, fi in zip(roots, fifths):
        bass += [r, '.', r, '.', fi, '.', r, '.', r, '.', fi, '.', r, '.', fi, '.']
    _play_pattern(buf, ' '.join(bass), step, TI(0.55))
    lead = ("A4 . C5 . E5 . C5 . A4 - . . E4 G4 A4 . "
            "C5 . A4 . F4 . A4 . C5 - . . D5 C5 A4 . "
            "E5 . G5 . C5 . E5 . G5 - . . E5 . D5 . "
            "D5 . B4 . G4 . B4 . D5 - . . D5 E5 D5 B4 "
            "A4 . C5 . E5 . C5 . A4 - . . E4 G4 A4 . "
            "C5 . A4 . F4 . A4 . C5 - . . D5 C5 A4 . "
            "E5 . G5 . C5 . E5 . G5 - . . A5 . G5 . "
            "D5 . B4 . G4 . A4 . B4 . C5 . E5 D5 B4 .")
    _play_pattern(buf, lead, step, PI(0.25, 0.17, vib=0.006))
    arps = {'A': ['A3', 'C4', 'E4', 'C4'], 'F': ['F3', 'A3', 'C4', 'A3'],
            'C': ['C4', 'E4', 'G4', 'E4'], 'G': ['G3', 'B3', 'D4', 'B3']}
    atoks = []
    for c in ['A', 'F', 'C', 'G'] * 2: atoks += arps[c] * 4
    _play_pattern(buf, ' '.join(atoks), step, PI(0.125, 0.075, ENV_PLUCK))
    _drums(buf, bars, step, 'rock')
    tracks['battle'] = _mix(buf, 0.85, crush=5)
    step = 60 / 150 / 4; bars = 8
    buf = _newbuf(step * 16 * bars + 0.05)
    bass_bars = [
        "D2 . D2 D3 D2 . D2 D3 D2 . D2 D3 D2 D3 C3 Bb2",
        "Bb1 . Bb1 Bb2 Bb1 . Bb1 Bb2 Bb1 . Bb1 Bb2 Bb1 Bb2 A2 G2",
        "C2 . C2 C3 C2 . C2 C3 C2 . C2 C3 C2 C3 Bb2 A2",
        "A1 . A1 A2 A1 . A1 A2 A1 . A1 A2 A1 A2 G2 E2",
    ] * 2
    _play_pattern(buf, ' '.join(bass_bars), step, TI(0.60), gate=0.95)
    lead_bars = [
        "D5 . D5 F5 . E5 . D5 C#5 . D5 . E5 . - .",
        "F5 . F5 A5 . G5 . F5 E5 . F5 . G5 . - .",
        "A5 . A5 . G5 F5 E5 . F5 . E5 . D5 . C#5 .",
        "D5 - . . A4 . D5 . F5 . E5 D5 C#5 . D5 .",
    ] * 2
    _play_pattern(buf, ' '.join(lead_bars), step, PI(0.5, 0.15))
    trem = {'D': ['D4', 'F4', 'A4', 'F4'], 'B': ['Bb3', 'D4', 'F4', 'D4'],
            'C': ['C4', 'E4', 'G4', 'E4'], 'A': ['A3', 'C#4', 'E4', 'C#4']}
    ttoks = []
    for c in ['D', 'B', 'C', 'A'] * 2: ttoks += trem[c] * 4
    _play_pattern(buf, ' '.join(ttoks), step, PI(0.125, 0.06, ENV_PLUCK))
    _drums(buf, bars, step, 'four', hatvol=0.18)
    tracks['boss'] = _mix(buf, 0.9, crush=4)
    step = 60 / 96 / 4; bars = 4
    buf = _newbuf(step * 16 * bars + 0.05)
    _play_pattern(buf, "A2 " + "- " * 15 + "F2 " + "- " * 15 +
                       "C3 " + "- " * 15 + "G2 " + "- " * 15,
                  step, TI(0.5, ENV_FADE), gate=1.0)
    _play_pattern(buf, "E5 . . . C5 . . . A4 . . . B4 . C5 . "
                       "C5 . . . A4 . . . F4 . . . A4 . C5 . "
                       "E5 . . . G5 . . . E5 . . . D5 . C5 . "
                       "B4 . . . D5 . . . G4 . A4 . B4 . . .",
                  step, PI(0.5, 0.13, vib=0.008, vibhz=5.0))
    for b in range(bars):
        t0 = int(b * 16 * step * SR); st = int(step * SR)
        d_hat(buf, t0, 0.12); d_hat(buf, t0 + 8 * st, 0.12)
    tracks['menu'] = _mix(buf, 0.8, crush=5)
    return tracks

def _sfx_bank():
    s = {}
    def mk(dur, fn, vol=1.0, crush=5):
        b = _newbuf(dur); fn(b); return _mix(b, vol, crush)
    bank = []
    for v in range(3):
        f0 = 1350 + v * 90
        def fn(b, f0=f0):
            n = int(0.07 * SR)
            v_pulse(b, 0, n, f0, f0 * 0.32, 0.30, 0.25, _env(n, ENV_PLUCK))
            v_noise(b, 0, int(0.015 * SR), 0.10, 1)
        bank.append(mk(0.09, fn, 0.8))
    s['shoot'] = bank
    bank = []
    for v in range(2):
        f0 = 560 + v * 60
        def fn(b, f0=f0):
            n = int(0.10 * SR)
            v_pulse(b, 0, n, f0, f0 * 0.40, 0.26, 0.5, _env(n, ENV_PLUCK))
        bank.append(mk(0.12, fn, 0.7))
    s['eshoot'] = bank
    def f_hit(b):
        v_noise(b, 0, int(0.03 * SR), 0.30, 3)
        n = int(0.045 * SR)
        v_pulse(b, 0, n, 340, 180, 0.22, 0.125, _env(n, ENV_PLUCK))
    s['hit'] = [mk(0.06, f_hit, 0.65)]
    def f_boom(b):
        n = int(0.34 * SR)
        v_noise(b, 0, n, 0.50, 4, _env(n, ENV_FADE))
        n2 = int(0.26 * SR)
        v_tri(b, 0, n2, 140, 36, 0.65, _env(n2, ENV_FADE))
        n3 = int(0.10 * SR)
        v_pulse(b, 0, n3, 60, 40, 0.35, 0.5, _env(n3, ENV_FADE))
    s['boom'] = [mk(0.38, f_boom, 0.95, crush=4)]
    def f_big(b):
        n = int(0.80 * SR)
        v_noise(b, 0, n, 0.55, 5, _env(n, ENV_FADE))
        n2 = int(0.35 * SR)
        v_noise(b, 0, n2, 0.40, 2, _env(n2, ENV_FADE))
        n3 = int(0.70 * SR)
        v_tri(b, 0, n3, 110, 28, 0.70, _env(n3, ENV_FADE))
        for k in range(3):
            at = int((0.18 + 0.20 * k) * SR)
            v_noise(b, at, int(0.2 * SR), 0.30, 3, _env(int(0.2 * SR), ENV_FADE))
    s['bigboom'] = [mk(0.95, f_big, 1.0, crush=4)]
    def f_hurt(b):
        n = int(0.20 * SR)
        v_pulse(b, 0, n, 210, 70, 0.32, 0.5, _env(n, ENV_FADE))
        v_noise(b, 0, int(0.08 * SR), 0.22, 2, _env(int(0.08 * SR), ENV_FADE))
    s['hurt'] = [mk(0.24, f_hurt, 0.9)]
    def f_pickup(b):
        st = int(0.045 * SR)
        for i, nn in enumerate(('C5', 'E5', 'G5', 'C6')):
            n = int(0.06 * SR)
            v_pulse(b, i * st, n, nfreq(nn), None, 0.28, 0.125, _env(n, ENV_PLUCK))
        v_tri(b, 0, int(0.10 * SR), nfreq('C3'), None, 0.30, _env(int(0.10 * SR), ENV_HOLD))
    s['pickup'] = [mk(0.22, f_pickup, 0.85)]
    def f_shield(b):
        for nn, t0, du in (('G4', 0.00, 0.05), ('C5', 0.05, 0.05), ('E5', 0.10, 0.16)):
            n = int(du * SR)
            v_pulse(b, int(t0 * SR), n, nfreq(nn), None, 0.26, 0.25, _env(n, ENV_HOLD))
        v_noise(b, int(0.10 * SR), int(0.18 * SR), 0.06, 1, _env(int(0.18 * SR), ENV_FADE))
    s['shield'] = [mk(0.30, f_shield, 0.8)]
    def f_stasis(b):
        st = int(0.07 * SR)
        for i, nn in enumerate(('A5', 'E5', 'C5', 'A4', 'E4')):
            n = int(0.09 * SR)
            v_pulse(b, i * st, n, nfreq(nn), None, 0.22, 0.125, _env(n, ENV_PLUCK))
        v_noise(b, 0, int(0.5 * SR), 0.10, 1, _env(int(0.5 * SR), ENV_FADE))
    s['stasis'] = [mk(0.55, f_stasis, 0.8)]
    def f_od(b):
        n = int(0.30 * SR)
        v_pulse(b, 0, n, 220, 980, 0.25, 0.25, _env(n, ENV_RISE))
        st = int(0.05 * SR)
        for i, nn in enumerate(('C4', 'E4', 'G4', 'C5', 'E5', 'G5')):
            n2 = int(0.055 * SR)
            v_pulse(b, i * st, n2, nfreq(nn), None, 0.18, 0.125, _env(n2, ENV_PLUCK))
    s['overdrive'] = [mk(0.42, f_od, 0.85)]
    def f_dash(b):
        v_noise(b, 0, int(0.16 * SR), 0.30, 1, _env(int(0.16 * SR), ENV_FADE))
        n = int(0.12 * SR)
        v_pulse(b, 0, n, 320, 1250, 0.20, 0.25, _env(n, ENV_RISE))
    s['dash'] = [mk(0.18, f_dash, 0.8)]
    def f_warn(b):
        for k in range(4):
            f0 = 620 if k % 2 == 0 else 430
            n = int(0.20 * SR)
            v_pulse(b, int(k * 0.22 * SR), n, f0, f0 * 1.06, 0.22, 0.5, _env(n, ENV_HOLD))
        v_tri(b, 0, int(0.9 * SR), 55, 55, 0.30, _env(int(0.9 * SR), ENV_FADE))
    s['warn'] = [mk(0.95, f_warn, 0.85)]
    bank = []
    for v in range(4):
        semis = v * 3
        def fn(b, semis=semis):
            base = nfreq('E5') * 2 ** (semis / 12)
            for i, off in enumerate((0, 7)):
                n = int(0.05 * SR)
                v_pulse(b, int(i * 0.05 * SR), n, base * 2 ** (off / 12), None,
                        0.24, 0.25, _env(n, ENV_PLUCK))
        bank.append(mk(0.12, fn, 0.7))
    s['combo'] = bank
    def f_up(b):
        st = int(0.07 * SR)
        for i, nn in enumerate(('G4', 'C5', 'E5', 'G5', '-', 'C6')):
            if nn == '-': continue
            n = int(0.10 * SR)
            v_pulse(b, i * st, n, nfreq(nn), None, 0.26, 0.25, _env(n, ENV_HOLD))
        v_tri(b, 0, int(0.45 * SR), nfreq('C3'), None, 0.35, _env(int(0.45 * SR), ENV_HOLD))
    s['upgrade'] = [mk(0.55, f_up, 0.85)]
    st = 0.105
    b = _newbuf(st * 16 + 0.3)
    _play_pattern(b, "C5 E5 G5 C6 - - . G5 . . C6 - - - - -", st, PI(0.25, 0.30))
    _play_pattern(b, "C3 - - - G3 - - - C3 - - - C3 - - -", st, TI(0.40))
    s['clear'] = [_mix(b, 0.9)]
    st = 0.16
    b = _newbuf(st * 16 + 0.6)
    _play_pattern(b, "E5 . C5 . A4 . G4 . E4 . . . A3 - - -", st,
                  PI(0.5, 0.22, vib=0.01))
    _play_pattern(b, "A2 - - - F2 - - - E2 - - - A1 - - -", st, TI(0.45, ENV_FADE))
    s['gameover'] = [_mix(b, 0.85)]
    def f_ui(b):
        n = int(0.04 * SR)
        v_pulse(b, 0, n, 880, None, 0.20, 0.25, _env(n, ENV_PLUCK))
    s['ui'] = [mk(0.05, f_ui, 0.5)]
    def f_ready(b):
        for i, fr in enumerate((1050, 1400)):
            n = int(0.035 * SR)
            v_pulse(b, int(i * 0.045 * SR), n, fr, None, 0.16, 0.125, _env(n, ENV_PLUCK))
    s['ready'] = [mk(0.10, f_ready, 0.6)]
    def f_spawn(b):
        n = int(0.22 * SR)
        v_pulse(b, 0, n, 90, 460, 0.16, 0.125, _env(n, ENV_RISE))
        v_noise(b, 0, n, 0.12, 2, _env(n, ENV_RISE))
    s['spawn'] = [mk(0.24, f_spawn, 0.55)]
    bank = []
    for v in range(4):
        f0 = 700 + 190 * v
        def fn(b, f0=f0):
            n = int(0.05 * SR)
            v_pulse(b, 0, n, f0, None, 0.22, 0.5, _env(n, ENV_PLUCK))
            v_noise(b, 0, int(0.01 * SR), 0.08, 2)
        bank.append(mk(0.06, fn, 0.85))
    s['beep'] = bank
    for stg in (1, 2, 3):
        f0 = 440 * 2 ** (stg * 3 / 12)
        def fn(b, f0=f0):
            n = int(0.09 * SR)
            v_pulse(b, 0, n, f0, f0 * 1.4, 0.20, 0.25, _env(n, ENV_PLUCK))
        s[f'charge{stg}'] = [mk(0.11, fn, 0.7)]
    def f_zap(b):
        n = int(0.20 * SR)
        v_pulse(b, 0, n, 160, 1100, 0.28, 0.25, _env(n, ENV_RISE))
        v_noise(b, 0, int(0.14 * SR), 0.25, 2, _env(int(0.14 * SR), ENV_FADE))
        v_tri(b, 0, int(0.30 * SR), 80, 40, 0.40, _env(int(0.30 * SR), ENV_FADE))
    s['zap'] = [mk(0.34, f_zap, 0.9, crush=4)]
    def f_event(b):
        st = int(0.06 * SR)
        for i, nn in enumerate(('C4', 'F4', 'A4', 'C5', 'F5')):
            n = int(0.08 * SR)
            v_pulse(b, i * st, n, nfreq(nn), None, 0.24, 0.25, _env(n, ENV_HOLD))
    s['event'] = [mk(0.40, f_event, 0.8)]
    def f_elite(b):
        n = int(0.22 * SR)
        v_pulse(b, 0, n, nfreq('C4'), None, 0.20, 0.5, _env(n, ENV_HOLD))
        v_pulse(b, 0, n, nfreq('C#4') + 6, None, 0.20, 0.5, _env(n, ENV_HOLD))
        v_pulse(b, int(0.20 * SR), int(0.30 * SR), nfreq('G3'), nfreq('G3') * 0.97,
                0.24, 0.5, _env(int(0.30 * SR), ENV_HOLD))
    s['elite'] = [mk(0.55, f_elite, 0.8)]
    # ---- v4 weapon / world sounds ----
    def f_rail(b):
        n = int(0.18 * SR)
        v_pulse(b, 0, n, 1400, 180, 0.30, 0.125, _env(n, ENV_FADE))
        v_noise(b, 0, int(0.10 * SR), 0.25, 2, _env(int(0.10 * SR), ENV_FADE))
        v_tri(b, 0, int(0.26 * SR), 70, 45, 0.50, _env(int(0.26 * SR), ENV_FADE))
    s['rail'] = [mk(0.30, f_rail, 0.85, crush=4)]
    def f_flak(b):
        v_noise(b, 0, int(0.12 * SR), 0.45, 3, _env(int(0.12 * SR), ENV_FADE))
        n = int(0.08 * SR)
        v_pulse(b, 0, n, 300, 90, 0.35, 0.5, _env(n, ENV_FADE))
    s['flak'] = [mk(0.15, f_flak, 0.9)]
    def f_missile(b):
        v_noise(b, 0, int(0.20 * SR), 0.20, 1, _env(int(0.20 * SR), ENV_RISE))
        n = int(0.16 * SR)
        v_pulse(b, 0, n, 260, 520, 0.22, 0.25, _env(n, ENV_RISE))
    s['missile'] = [mk(0.22, f_missile, 0.75)]
    def f_cap(b):
        for i, nn in enumerate(('G4', 'D5')):
            n = int(0.11 * SR)
            v_pulse(b, int(i * 0.11 * SR), n, nfreq(nn), None, 0.26, 0.25,
                    _env(n, ENV_HOLD))
        v_tri(b, int(0.10 * SR), int(0.18 * SR), nfreq('G3'), None, 0.30,
              _env(int(0.18 * SR), ENV_HOLD))
    s['capture'] = [mk(0.30, f_cap, 0.8)]
    return s

def build_audio():
    global SR, _MIX_CH
    init = pygame.mixer.get_init()
    if init is None: return {}, {}
    SR, _size, _MIX_CH = init
    print("rendering chiptune audio ...")
    return _sfx_bank(), _build_tracks()

class Audio:
    THROTTLE = {'shoot': 0.045, 'eshoot': 0.055, 'hit': 0.04, 'combo': 0.10,
                'beep': 0.05, 'zap': 0.06, 'missile': 0.05}
    def __init__(self, sfx, tracks):
        self.sfx, self.tracks = sfx, tracks
        self.muted = False; self.music_name = None
        self.duck_t = 0.0; self.music_vol = 0.55; self.sfx_vol = 0.9
        self._last = {}
        try:
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(1)
            self.mch = pygame.mixer.Channel(0)
        except Exception:
            self.mch = None
    def _mvol(self):
        v = 0.0 if self.muted else self.music_vol
        return v * (0.35 if self.duck_t > 0 else 1.0)
    def update(self, dt):
        if self.duck_t > 0:
            self.duck_t -= dt
            if self.mch: self.mch.set_volume(self._mvol())
    def music(self, name):
        if name == self.music_name:
            if self.mch: self.mch.set_volume(self._mvol())
            return
        self.music_name = name
        if self.mch is None: return
        self.mch.stop()
        snd = self.tracks.get(name) if name else None
        if snd:
            self.mch.play(snd, loops=-1)
            self.mch.set_volume(self._mvol())
    def duck(self, t=0.5):
        self.duck_t = max(self.duck_t, t)
        if self.mch: self.mch.set_volume(self._mvol())
    def play(self, name, vol=1.0, var=None):
        bank = self.sfx.get(name)
        if not bank or self.muted: return
        now = pygame.time.get_ticks() / 1000.0
        if now - self._last.get(name, -9.0) < self.THROTTLE.get(name, 0.015): return
        self._last[name] = now
        snd = bank[min(max(0, var), len(bank) - 1)] if var is not None \
            else random.choice(bank)
        if snd:
            snd.set_volume(self.sfx_vol * vol)
            snd.play()
    def toggle(self):
        self.muted = not self.muted
        if self.mch: self.mch.set_volume(self._mvol())

# ================================================================ entities ==
class Bullet:
    def __init__(self, pos, ang, speed, hostile, dmg, color, pierce=0, r=4.0,
                 life=1.8, knock=0.05, homing=False, splash=0, ignite=False):
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2(math.cos(ang), math.sin(ang)) * speed
        self.hostile, self.dmg, self.color = hostile, dmg, color
        self.life = life; self.r = r
        self.pierce = pierce; self.hits = set()
        self.knock = knock
        self.homing = homing; self.splash = splash; self.ignite = ignite
        self.retarget = 0.0; self.tgt_id = 0

class Particle:
    def __init__(self, pos, vel, life, col, r=2.0):
        self.pos = pygame.Vector2(pos); self.vel = pygame.Vector2(vel)
        self.life = self.max = life; self.col, self.r = col, r
    def update(self, dt):
        self.pos += self.vel * dt
        self.vel *= max(0.0, 1 - 2.2 * dt)
        self.life -= dt
        return self.life > 0
    def draw(self, surf):
        k = max(0.0, self.life / self.max)
        pygame.draw.circle(surf, dim(self.col, 0.25 + 0.75 * k),
                           self.pos, max(1, int(self.r * k)))

class FloatText:
    def __init__(self, pos, txt, col, size=12, life=0.9, vy=-34):
        self.pos = pygame.Vector2(pos); self.txt = txt
        self.col, self.size, self.life, self.max, self.vy = col, size, life, life, vy
    def update(self, dt):
        self.pos.y += self.vy * dt; self.life -= dt
        return self.life > 0

class Pickup:
    R = 12
    def __init__(self, pos, kind):
        self.pos = pygame.Vector2(pos); self.kind = kind
        self.t = 0.0; self.life = 12.0
    def update(self, dt, game):
        self.t += dt; self.life -= dt
        if game.player.magnet and game.state == 'play':
            d = self.pos.distance_to(game.player.pos)
            if d < 300:
                self.pos += (game.player.pos - self.pos).normalize() * 260 * dt
        return self.life > 0
    def draw(self, surf):
        if self.life < 3 and int(self.t * 6) % 2 == 0: return
        cx, cy = int(self.pos.x), int(self.pos.y + math.sin(self.t * 3) * 3)
        c = {'med': COL['green'], 'shield': (110, 190, 255),
             'od': COL['gold'], 'stasis': (170, 235, 255)}[self.kind]
        pygame.draw.circle(surf, dim(c, 0.22), (cx, cy), self.R)
        pygame.draw.circle(surf, c, (cx, cy), self.R, 2)
        if self.kind == 'med':
            pygame.draw.rect(surf, c, (cx - 7, cy - 2, 14, 4))
            pygame.draw.rect(surf, c, (cx - 2, cy - 7, 4, 14))
        elif self.kind == 'shield':
            pygame.draw.arc(surf, c, (cx - 6, cy - 6, 12, 12), 0.4, math.pi - 0.4, 3)
        elif self.kind == 'od':
            pygame.draw.polygon(surf, c, [(cx, cy - 8), (cx + 3, cy - 2), (cx + 8, cy),
                                          (cx + 3, cy + 2), (cx, cy + 8), (cx - 3, cy + 2),
                                          (cx - 8, cy), (cx - 3, cy - 2)])
        else:
            for a in range(3):
                dx, dy = math.cos(a * math.pi / 3), math.sin(a * math.pi / 3)
                pygame.draw.line(surf, c, (cx - dx * 7, cy - dy * 7),
                                 (cx + dx * 7, cy + dy * 7), 2)

class Player:
    R = 12
    def __init__(self, pos):
        self.pos = pygame.Vector2(pos)
        self.hp = 100; self.maxhp = 100
        self.cool = 0.0; self.invuln = 0.0; self.aim = 0.0
        self.dmg_mult = 1.0; self.rate_mult = 1.0; self.spd_mult = 1.0
        self.bspd_mult = 1.0; self.dash_mult = 1.0
        self.shots = 1; self.pierce = 0; self.leech = 0
        self.magnet = False; self.up_counts = {}
        self.shield = 0; self.od_t = 0.0
        self.dash_t = 0.0; self.dash_cd = 0.0; self.dash_dir = pygame.Vector2(1, 0)
        self.charge_t = 0.0; self.charge = 0.0
        self._stage = 0; self._held = False
        self.weapon = 'PULSE'
        self.chill_on_hit = 0.0; self.burn_chance = 0.0; self.burn_all = False
        self.charge_fast = False; self.tags_owned = set()
    def rate(self, game=None):
        rt = WEAPONS[self.weapon]['rate'] * self.rate_mult
        if self.weapon == 'RAIL' and game and 'SPOOL' in game.syn: rt *= 0.8
        return rt
    def out_dmg(self, game):
        d = self.dmg_mult
        if 'ADREN' in game.syn and self.hp < self.maxhp * 0.5: d *= 1.10
        return d
    def try_dash(self, game):
        if self.dash_cd > 0: return
        k = pygame.key.get_pressed()
        d = pygame.Vector2((k[pygame.K_d] or k[pygame.K_RIGHT]) - (k[pygame.K_a] or k[pygame.K_LEFT]),
                           (k[pygame.K_s] or k[pygame.K_DOWN]) - (k[pygame.K_w] or k[pygame.K_UP]))
        if d.length_squared() == 0:
            d = pygame.Vector2(math.cos(self.aim), math.sin(self.aim))
        self.dash_dir = d.normalize()
        self.dash_t = 0.16
        self.dash_cd = 2.6 * self.dash_mult
        self.invuln = max(self.invuln, 0.30)
        game.play('dash')
    def _pellet(self, game, ang, w, dmg, life=None, homing=False, splash=0):
        nose = self.pos + pygame.Vector2(math.cos(ang), math.sin(ang)) * 16
        game.bullets.append(Bullet(
            nose, ang, w['spd'] * self.bspd_mult * random.uniform(0.95, 1.05),
            False, dmg, w['col'],
            pierce=w['pierce'] + self.pierce if not homing else 0,
            r=w['r'], life=life or w['life'], knock=w['knock'],
            homing=homing, splash=splash))
        game.stats['fired'] += 1
    def fire(self, game):
        w = WEAPONS[self.weapon]
        dm = self.out_dmg(game)
        if self.weapon == 'PULSE':
            base = self.aim
            angles = (base,) if self.shots < 3 else (base - 0.15, base, base + 0.15)
            for a in angles: self._pellet(game, a, w, 26 * dm)
            game.play('shoot')
        elif self.weapon == 'RAIL':
            self._pellet(game, self.aim, w, 88 * dm)
            game.shake = min(10, game.shake + 3)
            game.play('rail', 0.9)
        elif self.weapon == 'FLAK':
            n = w['pellets'] + (3 if self.up_counts.get('choke') else 0) \
                + (2 if 'CHOKE' in game.syn else 0)
            for _ in range(n):
                self._pellet(game, self.aim + random.uniform(-w['spread'], w['spread']),
                             w, w['dmg'] * dm)
            game.play('flak', 0.9)
        elif self.weapon == 'HOMING':
            n = w['pellets'] + (1 if self.up_counts.get('pod') else 0)
            splash = w['splash'] * (1.6 if self.up_counts.get('fuse') else 1.0)
            for _ in range(n):
                self._pellet(game, self.aim + random.uniform(-w['spread'], w['spread']),
                             w, w['dmg'] * dm, homing=True, splash=splash)
            game.play('missile', 0.8)
    def _fire_bolt(self, game):
        ch = self.charge
        nose = self.pos + pygame.Vector2(math.cos(self.aim), math.sin(self.aim)) * 18
        col = lerp((190, 240, 255), (255, 215, 90), ch)
        dmg = (40 + 90 * ch) * self.out_dmg(game) * \
              (1.3 if self.up_counts.get('charge') else 1.0)
        game.bullets.append(Bullet(nose, self.aim, 700 * self.bspd_mult, False,
                                   dmg, col, pierce=1 + int(round(2 * ch)),
                                   r=5 + 5 * ch, knock=0.12, ignite=True))
        game.stats['fired'] += 1
        for _ in range(6):
            game.particles.append(Particle(nose, (random.uniform(-90, 90),
                                           random.uniform(-90, 90)), 0.2, col, 2.5))
        game.shake = min(10, game.shake + 2 + 5 * ch)
        game.play('zap', 0.7 + 0.4 * ch)
    def update(self, dt, game):
        self.cool -= dt; self.invuln -= dt; self.dash_cd -= dt
        self.od_t = max(0.0, self.od_t - dt)
        if self.dash_t > 0:
            self.dash_t -= dt
            self.pos += self.dash_dir * 880 * dt
            game.particles.append(Particle(self.pos, -self.dash_dir * 60 + pygame.Vector2(
                random.uniform(-30, 30), random.uniform(-30, 30)), 0.25, (160, 230, 255), 2.5))
        else:
            k = pygame.key.get_pressed()
            mv = pygame.Vector2(
                (k[pygame.K_d] or k[pygame.K_RIGHT]) - (k[pygame.K_a] or k[pygame.K_LEFT]),
                (k[pygame.K_s] or k[pygame.K_DOWN]) - (k[pygame.K_w] or k[pygame.K_UP]))
            if mv.length_squared() > 0:
                mv.normalize_ip()
                self.pos += mv * 330 * self.spd_mult * dt
                game.particles.append(Particle(
                    self.pos - mv * 13, -mv * 90, 0.2, (80, 170, 255), 1.8))
        self.pos.x = _clamp(self.pos.x, 16, PLAY_W - 16)
        self.pos.y = _clamp(self.pos.y, 16, HEIGHT - 16)
        mx, my = pygame.mouse.get_pos()
        self.aim = math.atan2(my - self.pos.y, mx - self.pos.x)
        firing = pygame.mouse.get_pressed()[0] or pygame.key.get_pressed()[pygame.K_SPACE]
        # ---- charging (PULSE only) ----
        if self.weapon == 'PULSE':
            if firing:
                if not self._held: self.charge_t = 0.0
                self.charge_t += dt
                self._held = True
            else:
                if self._held and self.charge > 0: self._fire_bolt(game)
                self._held = False
                self.charge_t = 0.0; self.charge = 0.0; self._stage = 0
            win = 0.15 if self.charge_fast else 0.26
            charging = self.charge_t > win
            if charging:
                gain = 0.9 if self.charge_fast else 0.75
                self.charge = min(1.0, (self.charge_t - win) * gain)
                stage = min(3, int(self.charge * 3) + 1)
                if stage > self._stage:
                    self._stage = stage
                    game.play(f'charge{stage}', 0.7)
                if random.random() < 0.5:
                    a = random.uniform(0, 2 * math.pi)
                    p = self.pos + pygame.Vector2(math.cos(a), math.sin(a)) * (16 + 8 * self.charge)
                    game.particles.append(Particle(p, (-math.cos(a) * 40, -math.sin(a) * 40),
                                                   0.15, (255, 220, 120), 1.6))
        else:
            self._held = False; self.charge = 0.0
        if firing and self.cool <= 0 and not (self.weapon == 'PULSE' and self.charge_t > 0.10):
            self.cool = self.rate(game) * (0.5 if self.od_t > 0 else 1.0)
            self.fire(game)
    def draw(self, surf):
        blink = self.invuln > 0 and int(self.invuln * 14) % 2 == 0
        col = COL['gold'] if self.od_t > 0 else COL['player']
        col = dim(col, 0.35) if blink else col
        a = self.aim
        pts = [(self.pos.x + math.cos(t) * rr, self.pos.y + math.sin(t) * rr)
               for t, rr in ((a, 17), (a + 2.5, 11), (a + math.pi, 7), (a - 2.5, 11))]
        pygame.draw.polygon(surf, col, pts)
        pygame.draw.polygon(surf, (230, 250, 255), pts, 1)
        pygame.draw.line(surf, col, self.pos, self.pos +
                         pygame.Vector2(math.cos(a), math.sin(a)) * 58, 1)
        if self.weapon == 'PULSE' and self.charge > 0:
            nose = self.pos + pygame.Vector2(math.cos(a), math.sin(a)) * 18
            pygame.draw.circle(surf, lerp((190, 240, 255), (255, 215, 90), self.charge),
                               nose, int(3 + 6 * self.charge))
            for i in range(3):
                ang = pygame.time.get_ticks() * 0.01 + i * 2.09
                p = nose + pygame.Vector2(math.cos(ang), math.sin(ang)) * (13 + 7 * self.charge)
                pygame.draw.circle(surf, (255, 230, 150), p, 2)
        if self.shield > 0:
            pygame.draw.circle(surf, (110, 190, 255), self.pos, 21, 2)
        if self.invuln > 0 and not blink:
            pygame.draw.circle(surf, (140, 220, 255), self.pos, 24, 1)

class Enemy:
    _ids = 0
    def __init__(self, pos, kind, wave):
        Enemy._ids += 1; self.id = Enemy._ids
        st = TYPES[kind]
        self.kind = kind; self.st = st
        self.pos = pygame.Vector2(pos); self.vel = pygame.Vector2()
        self.max_speed = min(250, 112 + wave * 9) * st['speed']
        self.max_hp = (300 + wave * 40) if st.get('boss') \
            else min(150, 46 + wave * 8) * st['hp']
        self.hp = self.max_hp
        self.dmg = st['bdmg']; self.cdmg = st['cdmg']
        self.bspd = st['bspeed']; self.rof = st['rof']; self.frange = st['frange']
        self.kb = 0.15 if st.get('boss') else 1.0
        self.affix = None; self.elite_t = 0.0
        self.fuse = -1.0; self.beep_t = 0.0
        self.blink_t = 0.0; self.blink_on = False
        self.fire_timer = random.uniform(0.9, 1.7)
        self.ssign = random.choice((-1, 1))
        self.sflip = random.uniform(0.8, 1.8) if kind != 'WARDEN' else random.uniform(2.5, 4.0)
        self.flash = 0.0; self.face = 0.0
        self.spawn_t = 0.7
        self.minion_t = 7.0
        self.want = pygame.Vector2()
        self.debug = None; self.inputs = None
        self.hist = deque(maxlen=160)
        self.brain = get_brain(kind)
        self.phase = 1
        # statuses
        self.chill_t = 0.0; self.chill_acc = 0.0
        self.burn_t = 0.0; self.burn_dps = 0.0
        self.demo_t = 18.0
    def update(self, dt, game):
        # ---- burn DoT (always real-time) ----
        if self.burn_t > 0:
            self.burn_t -= dt
            self.hp -= self.burn_dps * dt
            if random.random() < dt * 10:
                game.particles.append(Particle(
                    self.pos + pygame.Vector2(random.uniform(-8, 8), random.uniform(-8, 8)),
                    (0, -40), 0.3, (255, 150, 60), 2.2))
            if self.hp <= 0:
                game.kill(self, 'burn'); return
        # ---- CHILL: the fuzzy brain lags at ~20 Hz ----
        chilled = self.chill_t > 0
        if chilled:
            self.chill_t -= dt
            self.chill_acc += dt
            if self.chill_acc < 0.048:
                return                      # brain frozen this frame -- visibly laggy
            dt = self.chill_acc             # run one fat, chunky tick
            self.chill_acc = 0.0
        self.flash -= dt
        if self.spawn_t > 0:
            self.spawn_t -= dt
            if random.random() < 0.3:
                game.particles.append(Particle(self.pos + pygame.Vector2(random.uniform(-20, 20),
                                               random.uniform(-20, 20)), (0, 0), 0.3,
                                               self.st['col'], 1.5))
        # ---- WARDEN phase II at 50% HP: swap in the second Mamdani bank ----
        if self.kind == 'WARDEN' and self.phase == 1 and self.hp <= self.max_hp * 0.5:
            self.phase = 2
            self.brain = get_brain('WARDEN_P2')
            self.max_speed *= 1.20; self.rof *= 1.30; self.dmg += 4
            game.burst(self.pos, COL['gold'], 24, 300)
            game.ring(self.pos, COL['gold'])
            game.play('warn'); game.shake = min(12, game.shake + 8)
            game.floats.append(FloatText(self.pos + (0, -40), 'WARDEN: PHASE II',
                                         COL['gold'], 18, 1.6, -18))
        to_p = game.player.pos - self.pos
        d = to_p.length() or 1e-6
        tdn = to_p / d
        self.face = math.atan2(tdn.y, tdn.x)
        danger = 0.0
        for b in game.bullets:
            if not b.hostile:
                dd = b.pos.distance_to(self.pos)
                if dd < 240: danger += 1.0 - dd / 240
        danger = min(1.0, danger)
        pa = math.atan2(self.pos.y - game.player.pos.y, self.pos.x - game.player.pos.x)
        diff = abs((pa - game.player.aim + math.pi) % (2 * math.pi) - math.pi)
        watch = max(0.0, 1 - diff / 0.75) * max(0.0, 1 - (d - 320) / 280)
        watch *= game.watch_scale                       # GHOST pilot halves this
        if game.event and game.event['name'] == 'FOG':
            watch *= 0.15
        pack = sum(1 for o in game.enemies
                   if o is not self and o.spawn_t <= 0
                   and o.pos.distance_to(self.pos) < 150)
        vals = {'dist': d, 'health': self.hp, 'danger': danger,
                'watch': watch, 'pack': min(1.0, pack / 2.5),
                'prey': _clamp(game.player.hp, 0, 140)}
        self.inputs = (d, self.hp, danger, watch, min(1.0, pack / 2.5), vals['prey'])
        out, fz, acts, mags = self.brain.think(vals)          # <-- fuzzy inference
        self.debug = dict(fz=fz, acts=acts, out=out, mags=mags)
        self.hist.append((out['approach'], out['strafe'], out['fire']))
        frozen = game.freeze_t > 0
        if self.spawn_t > 0 or frozen:
            return
        if self.affix == 'SWIFT':
            self.elite_t -= dt
            if self.elite_t <= 0:
                self.elite_t = 0.05
                game.particles.append(Particle(self.pos, (random.uniform(-15, 15),
                                               random.uniform(-15, 15)), 0.25,
                                               self.st['col'], 2))
        elif self.affix == 'REGEN':
            for o in game.enemies:
                if o is not self and o.spawn_t <= 0 and o.hp < o.max_hp \
                        and o.pos.distance_to(self.pos) < 130:
                    o.hp = min(o.max_hp, o.hp + 7 * dt)
            self.elite_t -= dt
            if self.elite_t <= 0:
                self.elite_t = 0.5
                game.particles.append(Particle(self.pos, (0, -25), 0.4,
                                               (118, 255, 142), 2.5))
        self.sflip -= dt
        if self.sflip <= 0:
            self.ssign *= -1
            self.sflip = random.uniform(0.8, 1.8) if self.kind != 'WARDEN' \
                else random.uniform(2.5, 4.0)
        perp = pygame.Vector2(-tdn.y, tdn.x)
        spd = self.max_speed * (0.72 if chilled else 1.0)
        desired = (tdn * out['approach'] * spd
                   + perp * (out['strafe'] * self.ssign) * spd * 0.85)
        desired *= game.dir_power
        for o in game.enemies:
            if o is not self:
                off = self.pos - o.pos; dd = off.length()
                if 0 < dd < 64:
                    desired += off * ((64 - dd) / dd) * 2.0
        self.want = desired
        self.vel += (desired - self.vel) * min(1.0, 5 * dt)
        self.pos += self.vel * dt
        m = self.st['R'] + 2
        if self.pos.x < m: self.pos.x = m; self.vel.x = abs(self.vel.x) * 0.5
        if self.pos.x > PLAY_W - m: self.pos.x = PLAY_W - m; self.vel.x = -abs(self.vel.x) * 0.5
        if self.pos.y < m: self.pos.y = m; self.vel.y = abs(self.vel.y) * 0.5
        if self.pos.y > HEIGHT - m: self.pos.y = HEIGHT - m; self.vel.y = -abs(self.vel.y) * 0.5
        if self.kind == 'BOMBER':
            if self.fuse < 0 and d < 150:
                self.fuse = 2.2; self.beep_t = 0.0
            if self.fuse < 0 and d < self.st['R'] + Player.R + 4:
                self.fuse = 0.32
            if self.fuse >= 0:
                self.fuse -= dt
                self.blink_t += dt * (2 + 6 * (1 - max(0.0, self.fuse) / 2.2))
                self.blink_on = (self.blink_t % 1.0) < 0.5
                self.beep_t -= dt
                if self.beep_t <= 0:
                    prog = (2.2 - max(0.0, self.fuse)) / 2.2
                    game.play('beep', 0.9, var=min(3, int(prog * 3.99)))
                    self.beep_t = max(0.10, self.fuse * 0.22)
                if self.fuse <= 0:
                    self.fuse = -2.0
                    game.explosion(self.pos, 120, 34, 60, self.st['col'])
                    game.kill(self)
                    return
        self.fire_timer -= dt
        if self.fire_timer <= 0 and out['fire'] > 0.22 and d < self.frange:
            spread = math.radians(5 + 11 * (1 - out['fire']))
            base = self.face
            shots = 5 if self.kind == 'WARDEN' else 1
            offs = [(-0.4 + 0.8 * i / (shots - 1)) if shots > 1 else 0.0
                    for i in range(shots)]
            for o in offs:
                ang = base + o + random.uniform(-spread, spread)
                game.bullets.append(Bullet(
                    self.pos + tdn * (self.st['R'] + 4), ang,
                    min(720, (290 + game.wave * 10) * self.bspd),
                    True, self.dmg, lighten(self.st['col'], 0.45),
                    r=5 if self.kind == 'WARDEN' else (4.5 if self.kind == 'SNIPER' else 4)))
            self.fire_timer = (1.2 / (0.3 + 0.7 * out['fire'])) / self.rof * game.dir_fire
            game.play('eshoot')
        if self.kind == 'WARDEN':
            self.minion_t -= dt
            if self.minion_t <= 0 and len(game.enemies) < 8:
                self.minion_t = 7.0
                game.spawn_enemy('GRUNT', self.pos +
                                 pygame.Vector2(random.uniform(-60, 60), random.uniform(-60, 60)))
        if self.cdmg > 0 and d < self.st['R'] + Player.R:
            game.hurt_player(self.cdmg, self.pos)
            self.vel -= tdn * 120
    def draw(self, surf, frozen=False):
        scale = 1.0 - max(0.0, self.spawn_t) / 0.7 if self.spawn_t > 0 else 1.0
        if scale <= 0.02: return
        col = self.st['col']
        if self.kind == 'WARDEN' and self.phase == 2:
            col = lerp(col, (255, 210, 120), 0.45)
        if frozen: col = lerp(col, (150, 225, 255), 0.6)
        elif self.chill_t > 0: col = lerp(col, (150, 225, 255), 0.35)
        elif self.kind == 'PHANTOM' and self.inputs and self.inputs[3] < 0.25:
            col = dim(col, 0.45)
        if self.kind == 'BOMBER' and self.fuse >= 0:
            col = lerp(col, (255, 90, 70), 0.35 + 0.55 * (1 - max(0.0, self.fuse) / 2.2))
        if self.blink_on: col = (255, 255, 255)
        if self.flash > 0: col = (255, 255, 255)
        a = self.face; R = self.st['R'] * scale
        pts = [(self.pos.x + math.cos(t) * rr * scale,
                self.pos.y + math.sin(t) * rr * scale)
               for t, rr in ((a, R + 2), (a + 2.3, R * 0.7),
                             (a + math.pi, R * 0.5), (a - 2.3, R * 0.7))]
        pygame.draw.polygon(surf, col, pts)
        pygame.draw.circle(surf, dim(col, 0.55), self.pos, int(4 * scale))
        if self.kind == 'WARDEN':
            ring = lighten(col, 0.3 if self.phase == 1 else 0.6)
            pygame.draw.circle(surf, ring, self.pos, int(R * 0.55), 2)
            if self.phase == 2:
                pygame.draw.circle(surf, COL['gold'], self.pos, int(R * 0.8), 1)
        if self.kind == 'BOMBER' and self.fuse >= 0:
            rr = int(120 * max(0.0, self.fuse) / 2.2) + 12
            pygame.draw.circle(surf, (255, 110, 80), self.pos, rr, 1)
        if self.affix:
            pulse = int(self.st['R'] + 4 + math.sin(pygame.time.get_ticks() * 0.006) * 1.5)
            pygame.draw.circle(surf, (255, 255, 255), self.pos, pulse, 1)
            tx, ty = int(self.pos.x), int(self.pos.y - self.st['R'] - 12)
            pygame.draw.polygon(surf, (255, 255, 255),
                                [(tx, ty - 4), (tx + 4, ty), (tx, ty + 4), (tx - 4, ty)])
        f = max(0.0, self.hp / self.max_hp)
        r = self.st['R'] + 7
        rect = pygame.Rect(int(self.pos.x) - r, int(self.pos.y) - r, 2 * r, 2 * r)
        pygame.draw.arc(surf, lerp(COL['red'], COL['green'], f), rect,
                        -math.pi / 2, -math.pi / 2 + 2 * math.pi * max(0.02, f), 2)
        if frozen:
            pygame.draw.circle(surf, (170, 235, 255), self.pos, self.st['R'] + 5, 1)

# ------------------------------------------------------- world hazards -----
class Sweeper:
    """Rotating laser pylon: telegraph -> live beam.  Hurts drones AND you."""
    LEN = 1150
    def __init__(self):
        side = random.randrange(4); m = 40
        if   side == 0: p = (random.uniform(m, PLAY_W - m), m)
        elif side == 1: p = (random.uniform(m, PLAY_W - m), HEIGHT - m)
        elif side == 2: p = (m, random.uniform(m, HEIGHT - m))
        else:           p = (PLAY_W - m, random.uniform(m, HEIGHT - m))
        self.pos = pygame.Vector2(p)
        self.ang = random.uniform(0, 2 * math.pi)
        self.spd = random.choice((-1, 1)) * random.uniform(0.45, 0.70)
        self.state = 'tel'; self.t = random.uniform(1.0, 1.8)
    def update(self, dt, game):
        self.t -= dt
        self.ang += self.spd * dt
        if self.t <= 0:
            if self.state == 'tel':
                self.state = 'live'; self.t = 3.0; game.play('warn', 0.5)
            elif self.state == 'live':
                self.state = 'off'; self.t = random.uniform(1.6, 2.6)
            else:
                self.state = 'tel'; self.t = 1.3
        if self.state != 'live': return
        d = pygame.Vector2(math.cos(self.ang), math.sin(self.ang))
        p = game.player
        if p.hp > 0:
            v = p.pos - self.pos; t = v.dot(d)
            if 0 <= t <= self.LEN and (v - d * t).length() < 9 + Player.R:
                game.hurt_player(16, self.pos + d * t)
        for e in list(game.enemies):
            if e.spawn_t > 0: continue
            v = e.pos - self.pos; t = v.dot(d)
            if 0 <= t <= self.LEN and (v - d * t).length() < 9 + e.st['R']:
                e.hp -= 30 * dt; e.flash = 0.05
                if random.random() < dt * 6:
                    game.particles.append(Particle(e.pos, (random.uniform(-60, 60),
                                                   random.uniform(-60, 60)), 0.2,
                                                   (255, 90, 90), 2))
                if e.hp <= 0: game.kill(e, 'laser')
    def draw(self, surf):
        d = pygame.Vector2(math.cos(self.ang), math.sin(self.ang))
        end = self.pos + d * self.LEN
        pygame.draw.circle(surf, (150, 60, 70), self.pos, 8)
        pygame.draw.circle(surf, (255, 120, 120), self.pos, 8, 2)
        if self.state == 'tel':
            steps = int(self.LEN / 18)
            for i in range(0, steps, 2):
                a = self.pos + d * (i * 18); b = self.pos + d * (i * 18 + 9)
                pygame.draw.line(surf, (120, 50, 60), a, b, 1)
        elif self.state == 'live':
            pygame.draw.line(surf, (255, 80, 90), self.pos, end, 5)
            pygame.draw.line(surf, (255, 230, 230), self.pos, end, 2)

class Crumble:
    def __init__(self, rect, seed):
        self.rect = rect; self.heat = 0.0; self.dead = False
        rnd = random.Random(seed)
        self.cracks = []
        c = pygame.Vector2(rect.center)
        for _ in range(5):
            a = rnd.uniform(0, 2 * math.pi)
            pts = [c]
            p = c
            for k in range(3):
                p = p + pygame.Vector2(math.cos(a), math.sin(a)) * rnd.uniform(10, 20)
                a += rnd.uniform(-0.7, 0.7)
                pts.append(p)
            self.cracks.append(pts)
    def update(self, dt, game):
        if self.dead: return
        on = self.rect.collidepoint((game.player.pos.x, game.player.pos.y)) \
            and game.player.hp > 0
        if not on:
            for e in game.enemies:
                if e.spawn_t <= 0 and self.rect.collidepoint((e.pos.x, e.pos.y)):
                    on = True; break
        self.heat = self.heat + dt if on else max(0.0, self.heat - dt * 0.7)
        if self.heat >= 1.1:
            self.dead = True
            game.explosion(pygame.Vector2(self.rect.center), 95, 18, 38,
                           (255, 170, 90), harm_player=True, hitstop=0.05, quiet=True)
    def draw(self, surf):
        r = self.rect
        if self.dead:
            pygame.draw.rect(surf, (8, 9, 14), r)
            pygame.draw.rect(surf, (28, 32, 44), r, 1)
            return
        pygame.draw.rect(surf, (22, 19, 20), r)
        k = int(self.heat * 5) + 1
        for pts in self.cracks[:k]:
            pygame.draw.lines(surf, (90, 70, 60), False, pts, 1)
        pygame.draw.rect(surf, lerp((50, 40, 38), (255, 140, 70), self.heat), r, 1)

class Turret:
    """Neutral node.  Stand on it to capture; it then hunts targets with the
    HOMING fuzzy scorer.  Drones can steal it back for the enemy."""
    R = 15
    def __init__(self, pos):
        self.pos = pygame.Vector2(pos)
        self.cap = 0.0; self.cool = 1.0; self.flash = 0.0
        self.aim = 0.0; self.t = random.uniform(0, 6)
    def owner(self):
        return 'P' if self.cap > 0.6 else 'E' if self.cap < -0.6 else 'N'
    def update(self, dt, game):
        self.t += dt; self.flash -= dt
        p = game.player
        near_p = p.hp > 0 and p.pos.distance_to(self.pos) < 62
        near_e = any(e.spawn_t <= 0 and e.pos.distance_to(self.pos) < 62
                     for e in game.enemies)
        old = self.owner()
        if near_p: self.cap = min(1.0, self.cap + dt / 1.8)
        if near_e: self.cap = max(-1.0, self.cap - dt / 2.4)
        new = self.owner()
        if new != old:
            if new == 'P':
                game.meta['totals']['turret'] += 1
                game.meta_check()
                game.play('capture')
                game.floats.append(FloatText(self.pos, 'NODE CAPTURED',
                                             (120, 255, 170), 12, 1.2, -26))
            elif new == 'E':
                game.play('warn', 0.35)
                game.floats.append(FloatText(self.pos, 'NODE LOST',
                                             (255, 110, 110), 12, 1.2, -26))
        self.cool -= dt
        if self.cool > 0: return
        if self.owner() == 'P':
            best, bs = None, -9.0
            for e in game.enemies:
                if e.spawn_t > 0: continue
                sc, fz, acts = target_score(e, self.pos)   # fuzzy target pick
                if sc > bs: bs, best = sc, e
            if best and bs > 0.15:
                self.aim = math.atan2(best.pos.y - self.pos.y, best.pos.x - self.pos.x)
                d = pygame.Vector2(math.cos(self.aim), math.sin(self.aim))
                game.bullets.append(Bullet(self.pos + d * 18, self.aim, 540, False,
                                           20, (170, 240, 255)))
                self.cool = 0.85; self.flash = 0.10
                game.play('eshoot', 0.3, 0)
            else:
                self.cool = 0.35
        elif self.owner() == 'E':
            self.aim = math.atan2(p.pos.y - self.pos.y, p.pos.x - self.pos.x)
            d = pygame.Vector2(math.cos(self.aim), math.sin(self.aim))
            game.bullets.append(Bullet(self.pos + d * 18, self.aim, 400, True,
                                       9, (255, 140, 140)))
            self.cool = 1.5; self.flash = 0.10
        else:
            self.cool = 0.5
    def draw(self, surf):
        oc = {'P': (120, 220, 255), 'E': (255, 110, 110), 'N': (150, 160, 180)}[self.owner()]
        pts = [(self.pos.x + math.cos(a * math.pi / 3 + 0.5) * self.R,
                self.pos.y + math.sin(a * math.pi / 3 + 0.5) * self.R)
               for a in range(6)]
        pygame.draw.polygon(surf, dim(oc, 0.35), pts)
        pygame.draw.polygon(surf, oc, pts, 2)
        pygame.draw.circle(surf, oc, self.pos, 4)
        pygame.draw.line(surf, oc, self.pos, self.pos +
                         pygame.Vector2(math.cos(self.aim), math.sin(self.aim)) * 20, 2)
        rr = pygame.Rect(int(self.pos.x) - 18, int(self.pos.y) - 18, 36, 36)
        frac = abs(self.cap)
        pygame.draw.arc(surf, lerp((90, 90, 110), oc, frac), rr, -math.pi / 2,
                        -math.pi / 2 + 2 * math.pi * max(0.02, frac), 2)
        if self.flash > 0:
            pygame.draw.circle(surf, (255, 255, 255), self.pos, 6, 1)

# ------------------------------------------------------- upgrades / relics --
UPGRADES = [
 dict(key='dmg', tags=('power',), pool=('any',), name='OVERCALIBRATE',
      desc=('+35% bullet damage',), can=lambda p: True,
      apply=lambda p: setattr(p, 'dmg_mult', p.dmg_mult * 1.35)),
 dict(key='rate', tags=('fire',), pool=('any',), name='RAPID LOADER',
      desc=('+25% fire rate',), can=lambda p: True,
      apply=lambda p: setattr(p, 'rate_mult', p.rate_mult * 0.78)),
 dict(key='spd', tags=('move',), pool=('any',), name='SERVO LEGS',
      desc=('+15% move speed',), can=lambda p: True,
      apply=lambda p: setattr(p, 'spd_mult', p.spd_mult * 1.15)),
 dict(key='tri', tags=('fire',), pool=('PULSE',), name='TRI-BARREL',
      desc=('fire 3 bullets in a spread',), can=lambda p: p.shots < 3,
      apply=lambda p: setattr(p, 'shots', 3)),
 dict(key='pierce', tags=('power', 'rail'), pool=('PULSE', 'RAIL'), name='RAILCORE',
      desc=('bullets pierce +1 drone',), can=lambda p: p.pierce < 2,
      apply=lambda p: setattr(p, 'pierce', p.pierce + 1)),
 dict(key='hull', tags=('body',), pool=('any',), name='REINFORCED HULL',
      desc=('+25 max hull, heal 25',), can=lambda p: True,
      apply=lambda p: (setattr(p, 'maxhp', p.maxhp + 25),
                       setattr(p, 'hp', min(p.maxhp, p.hp + 25)))),
 dict(key='leech', tags=('body', 'risk'), pool=('any',), name='NANO LEECH',
      desc=('+2 hull per kill',), can=lambda p: p.leech < 4,
      apply=lambda p: setattr(p, 'leech', p.leech + 2)),
 dict(key='mag', tags=('move',), pool=('any',), name='MAGNET FIELD',
      desc=('pickups fly to you',), can=lambda p: not p.magnet,
      apply=lambda p: setattr(p, 'magnet', True)),
 dict(key='dash', tags=('move',), pool=('any',), name='PHASE DASH',
      desc=('-30% dash cooldown',), can=lambda p: p.dash_mult > 0.4,
      apply=lambda p: setattr(p, 'dash_mult', p.dash_mult * 0.7)),
 dict(key='bspd', tags=('fire',), pool=('any',), name='HOT ROUNDS',
      desc=('+25% bullet speed',), can=lambda p: True,
      apply=lambda p: setattr(p, 'bspd_mult', p.bspd_mult * 1.25)),
 dict(key='cryo', tags=('element',), pool=('any',), name='CRYO ROUNDS',
      desc=('hits chill 0.9s', 'chilled brains lag at 20Hz'), can=lambda p: p.chill_on_hit < 1,
      apply=lambda p: setattr(p, 'chill_on_hit', 0.9)),
 dict(key='pyro', tags=('element',), pool=('any',), name='INCENDIARY',
      desc=('50% chance to ignite', 'burn = director pressure'), can=lambda p: p.burn_chance < 0.5,
      apply=lambda p: setattr(p, 'burn_chance', 0.5)),
 dict(key='choke', tags=('flak', 'fire'), pool=('FLAK',), name='WIDE CHOKE',
      desc=('+3 pellets per shot',), can=lambda p: not p.up_counts.get('choke'),
      apply=lambda p: setattr(p, 'up_counts', {**p.up_counts, 'choke': 1})),
 dict(key='pod', tags=('homing', 'fire'), pool=('HOMING',), name='SWARM PODS',
      desc=('+1 missile per volley',), can=lambda p: not p.up_counts.get('pod'),
      apply=lambda p: setattr(p, 'up_counts', {**p.up_counts, 'pod': 1})),
 dict(key='fuse', tags=('homing', 'power'), pool=('HOMING',), name='SMART FUSE',
      desc=('+60% missile splash',), can=lambda p: not p.up_counts.get('fuse'),
      apply=lambda p: setattr(p, 'up_counts', {**p.up_counts, 'fuse': 1})),
 dict(key='spool', tags=('rail', 'fire'), pool=('RAIL',), name='OVERSPOOL',
      desc=('-25% rail cooldown',), can=lambda p: not p.up_counts.get('spool'),
      apply=lambda p: setattr(p, 'up_counts', {**p.up_counts, 'spool': 1})),
 dict(key='charge', tags=('pulse', 'fire'), pool=('PULSE',), name='HYPERCAPACITOR',
      desc=('charge 40% faster', 'charged bolt +30% dmg'), can=lambda p: not p.up_counts.get('charge'),
      apply=lambda p: (setattr(p, 'up_counts', {**p.up_counts, 'charge': 1}),
                       setattr(p, 'charge_fast', True))),
]

RELICS = [
 dict(key='R_GLASS', name='GLASS CANNON', tags=('power', 'risk'),
      desc=('+60% damage', 'max hull cut to 70'),
      apply=lambda g: (setattr(g.player, 'dmg_mult', g.player.dmg_mult * 1.6),
                       setattr(g.player, 'maxhp', min(g.player.maxhp, 70)),
                       setattr(g.player, 'hp', min(g.player.hp, g.player.maxhp)))),
 dict(key='R_DIRE', name='DIRE DEAL', tags=('meta', 'risk'),
      desc=('director ignores your bias', '+50% score'),
      apply=lambda g: setattr(g, 'relic_dire', True)),
 dict(key='R_THIN', name='BLOOD PACT', tags=('risk',),
      desc=('drones 18% faster', '+35% score'),
      apply=lambda g: setattr(g, 'relic_score', g.relic_score + 0.35)),
 dict(key='R_VAMP', name='VAMPIRE PROTOCOL', tags=('power', 'risk'),
      desc=('heal 4 per kill', 'director intensity +0.15'),
      apply=lambda g: (setattr(g.player, 'leech', g.player.leech + 4),
                       setattr(g, 'relic_vamp', True))),
 dict(key='R_ZERO', name='ZERO FIELD', tags=('element',),
      desc=('every hit chills 1.2s', 'fire rate -12%'),
      apply=lambda g: (setattr(g.player, 'chill_on_hit', max(g.player.chill_on_hit, 1.2)),
                       setattr(g.player, 'rate_mult', g.player.rate_mult * 1.12))),
 dict(key='R_EMBER', name='EMBER CORE', tags=('element', 'power'),
      desc=('every hit ignites', 'you take +25% damage'),
      apply=lambda g: setattr(g, 'relic_ember', True)),
 dict(key='R_TITAN', name='TITAN SHELL', tags=('body', 'risk'),
      desc=('+60 max hull', 'move 15% slower, dash slower'),
      apply=lambda g: (setattr(g.player, 'maxhp', g.player.maxhp + 60),
                       setattr(g.player, 'hp', g.player.hp + 60),
                       setattr(g.player, 'spd_mult', g.player.spd_mult * 0.85),
                       setattr(g.player, 'dash_mult', g.player.dash_mult * 1.4))),
 dict(key='R_GREED', name='DRAGON HOARD', tags=('meta', 'risk'),
      desc=('pickups 50% rarer', '+40% score'),
      apply=lambda g: (setattr(g, 'relic_greed', True),
                       setattr(g, 'relic_score', g.relic_score + 0.40))),
]

SYNERGIES = [
 ('THERMAL', ('power', 'element'), 'THERMAL MIX', 'statuses 50% stronger'),
 ('SPOOL',   ('fire', 'rail'),     'OVERSPOOL+',  'rail cooldown -20% more'),
 ('CHOKE',   ('flak', 'power'),    'HEAVY CHOKE', '+2 more flak pellets'),
 ('FROST',   ('homing', 'element'),'SEEKER FROST','missile splash chills'),
 ('ADREN',   ('risk', 'fire'),     'ADRENALINE',  '+10% dmg under 50% hull'),
]

def _font(sz):
    try:    return pygame.font.SysFont("consolas,menlo,dejavusansmono,monospace", sz)
    except Exception: return pygame.font.Font(None, sz)

# ============================================================ panel drawing =
def draw_chart(surf, rect, fvar, value, degrees, tiny):
    pygame.draw.rect(surf, (17, 22, 32), rect)
    pygame.draw.rect(surf, (55, 70, 95), rect, 1)
    pad = 5
    base, top = rect.bottom - 15, rect.top + 3
    H = base - top
    px = lambda v: rect.left + pad + (v - fvar.lo) / (fvar.hi - fvar.lo) * (rect.w - 2 * pad)
    pygame.draw.line(surf, (70, 85, 110), (rect.left + 2, base), (rect.right - 2, base))
    for i, (sn, mf) in enumerate(fvar.sets):
        col = SET_COLORS[i % len(SET_COLORS)]
        deg = degrees.get(sn, 0.0)
        line, fill = [], []
        for k in range(33):
            v = fvar.lo + (fvar.hi - fvar.lo) * k / 32
            mu = mf(v)
            line.append((px(v), base - mu * H))
            fill.append((px(v), base - min(mu, deg) * H))
        if deg > 0.02:
            pygame.draw.polygon(surf, dim(col, 0.30 + 0.35 * deg),
                                [(rect.left + pad, base)] + fill + [(rect.right - pad, base)])
        pygame.draw.lines(surf, dim(col, 0.95), False, line, 1)
        lx, ly = min(line, key=lambda p: p[1])
        surf.blit(tiny.render(sn, True, dim(col, 0.9)),
                  (min(max(lx + 2, rect.left + 2), rect.right - 34), max(top, ly - 10)))
        if deg > 0.02:
            img = tiny.render(f"{deg:.2f}", True, col)
            surf.blit(img, (rect.right - img.get_width() - 3, top + 1 + i * 10))
    vx = px(_clamp(value, fvar.lo, fvar.hi))
    pygame.draw.line(surf, (240, 245, 255), (vx, top), (vx, base), 1)
    pygame.draw.polygon(surf, (240, 245, 255), [(vx - 3, top), (vx + 3, top), (vx, top + 5)])
    vs = f"{value:.2f}" if fvar.hi <= 1.5 else f"{value:.0f}"
    surf.blit(tiny.render(f"{fvar.name} = {vs}", True, COL['dim']), (rect.left + 4, base + 2))

def draw_telemetry(surf, rect, hist, tiny):
    pygame.draw.rect(surf, (14, 18, 26), rect)
    pygame.draw.rect(surf, (55, 70, 95), rect, 1)
    mid = rect.centery
    pygame.draw.line(surf, (60, 74, 98), (rect.left + 2, mid), (rect.right - 2, mid), 1)
    surf.blit(tiny.render("TELEMETRY ~2.5s", True, COL['dim']), (rect.left + 4, rect.top + 2))
    if len(hist) < 2: return
    n = len(hist)
    for idx, col in enumerate((SYS_COL['approach'], SYS_COL['strafe'], SYS_COL['fire'])):
        lo, hi = (0, 1) if idx == 2 else (-1, 1)
        pts = [(rect.left + (rect.w - 6) * i / (n - 1) + 3,
                rect.bottom - 4 - (_clamp(h[i][idx], lo, hi) - lo) / (hi - lo) * (rect.h - 14))
               for i, h in enumerate(hist)]
        pygame.draw.lines(surf, col, False, pts, 1)

def draw_ihist(surf, rect, hist, tiny):
    pygame.draw.rect(surf, (14, 18, 26), rect)
    pygame.draw.rect(surf, (55, 70, 95), rect, 1)
    surf.blit(tiny.render("INTENSITY ~2.6s", True, COL['dim']), (rect.left + 4, rect.top + 2))
    if len(hist) < 2: return
    n = len(hist)
    pts = [(rect.left + (rect.w - 6) * i / (n - 1) + 3,
            rect.bottom - 4 - _clamp(v, 0, 1) * (rect.h - 14))
           for i, v in enumerate(hist)]
    pygame.draw.lines(surf, COL['gold'], False, pts, 1)

def draw_mamdani(surf, rect, pts, ovar, crisp, tiny):
    pygame.draw.rect(surf, (14, 18, 26), rect)
    pygame.draw.rect(surf, (55, 70, 95), rect, 1)
    top, base = rect.top + 6, rect.bottom - 14
    px = lambda x: rect.left + 6 + (x - ovar.lo) / (ovar.hi - ovar.lo) * (rect.w - 12)
    pygame.draw.line(surf, (70, 85, 110), (rect.left + 4, base), (rect.right - 4, base))
    surf.blit(tiny.render("MAMDANI AGGREGATE -> CENTROID", True, COL['dim']),
              (rect.left + 4, rect.top + 2))
    for name, mf in ovar.sets:
        line = [(px(x), base - mf(x) * (base - top - 12)) for x, _ in pts]
        pygame.draw.lines(surf, (48, 60, 82), False, line, 1)
    poly = [(px(x), base - m * (base - top - 12)) for x, m in pts if m > 0]
    if len(poly) >= 2:
        pygame.draw.polygon(surf, dim(COL['gold'], 0.55),
                            [(px(pts[0][0]), base)] + poly + [(px(pts[-1][0]), base)])
        pygame.draw.lines(surf, COL['gold'], False, poly, 1)
    cx = px(_clamp(crisp, -1, 1))
    pygame.draw.line(surf, (245, 250, 255), (cx, top + 10), (cx, base), 1)
    for nm, xx in (('RET', -0.75), ('HOLD', 0.0), ('ADV', 0.75)):
        surf.blit(tiny.render(nm, True, COL['dim']), (px(xx) - 8, base + 2))

# ==================================================================== game ==
class Game:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 1, 256)
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("FUZZY BOT ARENA : WAR MACHINE")
        self.clock = pygame.time.Clock()
        self.f_big, self.f_med = _font(46), _font(24)
        self.f_base, self.f_small, self.f_tiny = _font(15), _font(12), _font(10)
        self.world = pygame.Surface((PLAY_W, HEIGHT))
        sfx, tracks = build_audio()
        self.audio = Audio(sfx, tracks)
        self.show_panel = True; self.time_scale = 1.0
        self.focus_manual = False; self.focus_i = 0
        self.panel_page = 0
        self.crt = False
        self.scan = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        for yy in range(0, HEIGHT, 3):
            pygame.draw.line(self.scan, (0, 0, 0, 30), (0, yy), (PLAY_W, yy))
        self.meta = load_meta()
        self.toasts = []
        self.reset()
        self.state = 'menu'
        self.sel_p = 0; self.sel_w = 0
        last = self.meta.get('last')
        if last:
            if last.get('pilot') in PILOT_ORDER: self.sel_p = PILOT_ORDER.index(last['pilot'])
            if last.get('weapon') in WEAPON_ORDER: self.sel_w = WEAPON_ORDER.index(last['weapon'])
        self.sel_rects = []
        self.demo_kinds = ['GRUNT', 'RUSHER', 'SNIPER', 'PHANTOM', 'BOMBER']
        self.demo_t = 0.5; self.menu_t = 0.0
        self.audio.music('menu')

    def reset(self):
        self.player = Player((PLAY_W / 2, HEIGHT / 2))
        self.pilot = 'ACE'
        self.bullets, self.enemies, self.particles, self.packs = [], [], [], []
        self.floats, self.fx_rings = [], []
        self.crumbs, self.turrets, self.sweepers = [], [], []
        self.score = 0; self.wave = 0; self.spawn_queue = []
        self.spawn_t = 0.0; self.spawn_gap = 1.0; self.clear_t = 0.0
        self.shake = 0.0; self.flash = 0.0; self.flash_col = (255, 60, 60)
        self.freeze_t = 0.0; self.streak = 0; self.streak_t = 0.0
        self.boss_warn_t = 0.0; self.choices = []; self.card_rects = []
        self._dash_was = 0.0; self.jingle_t = 0.0
        self.hitstop = 0.0
        self.event = None; self.storm_t = 0.0
        self.relics = []; self.syn = set(); self.syn_elem = 1.0; self.syn_frost = False
        self.relic_score = 0.0
        self.relic_dire = self.relic_greed = False
        self.relic_ember = self.relic_vamp = self.relic_thin = False
        self.watch_scale = 1.0
        self.wave_dmg = 0
        self.rec = []; self.rec_t = 0.0
        self.dir_intensity = 0.45; self.dir_bias = 0.0
        self.dir_power = 1.0; self.dir_fire = 1.0
        self.dir_gap = 1.0; self.dir_care = 0.5
        self.dir_dbg = None; self.dir_hist = deque(maxlen=160)
        self.dmg_log = deque()
        self.last_clear_norm = 0.5; self.wave_start = 0.0
        self.stats = dict(fired=0, hits=0, dmg=0, best_mult=1, time=0.0, kills={})

    # ---- lifecycle -----------------------------------------------------
    def score_mult(self):
        m = 1.0
        if self.pilot == 'GHOST': m *= 0.85
        m *= 1.0 + self.relic_score
        if self.relic_dire: m *= 1.5
        return m

    def start_game(self):
        pilot = PILOT_ORDER[self.sel_p]
        weapon = WEAPON_ORDER[self.sel_w]
        self.reset()
        self.pilot = pilot
        pl = self.player
        pl.weapon = weapon
        pl.tags_owned = {WEAPONS[weapon]['tag']}
        if pilot == 'NOVA':
            pl.maxhp = 80; pl.hp = 80; pl.charge_fast = True
        elif pilot == 'BULWARK':
            pl.maxhp = 140; pl.hp = 140; pl.spd_mult *= 0.88; pl.shield = 1
        elif pilot == 'GHOST':
            self.watch_scale = 0.5
        self.meta['last'] = {'pilot': pilot, 'weapon': weapon}
        save_meta(self.meta)
        self.start_wave(1)
        self.focus_manual = False; self.focus_i = 0
        self.state = 'play'
        self.audio.music('battle')
        self.play('ui')

    def start_wave(self, n):
        self.wave = n
        self.audio.music('boss' if n % 5 == 0 else 'battle')
        self.wave_start = pygame.time.get_ticks() / 1000.0
        self.event = None
        self.wave_dmg = 0
        self.make_hazards(n)
        q = []
        if n % 5 == 0:
            q = ['WARDEN'] + ['GRUNT'] * (1 + n // 5)
            self.boss_warn_t = 2.4
            self.play('warn')
        else:
            pools = [['GRUNT']] * min(2 + n, 8)
            if n >= 3: pools.append(['RUSHER'] * min(1 + (n - 3) // 2, 4))
            if n >= 4: pools.append(['SNIPER'] * min(1 + (n - 4) // 2, 3))
            if n >= 5: pools.append(['BOMBER'] * min(1 + (n - 5) // 2, 3))
            if n >= 6: pools.append(['PHANTOM'] * min(1 + (n - 6) // 3, 2))
            while any(pools):
                for p in pools:
                    if p: q.append(p.pop())
            q = q[:14]
            random.shuffle(q)
            if n >= 4 and random.random() < 0.40:
                name = random.choice(('GOLD', 'STORM', 'FOG'))
                dur = 11.0 if name == 'STORM' else 9999.0
                self.event = dict(name=name, t=dur, banner_t=3.2)
                labels = {'GOLD': 'SURGE: GOLD RUSH', 'STORM': 'SURGE: BULLET STORM',
                          'FOG': 'SURGE: FOG PROTOCOL'}
                self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2 - 90),
                                             labels[name], COL['gold'], 20, 2.2, -10))
                self.play('event')
        self.spawn_queue = q
        self.spawn_t = 2.4 if n % 5 == 0 else 0.8
        self.spawn_gap = max(0.45, 1.25 - 0.06 * n)
        self.clear_t = 0.0
        self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2 - 40),
                                     f"WAVE {n}", COL['gold'], 24, 1.4, -12))

    def make_hazards(self, n):
        self.crumbs, self.turrets, self.sweepers = [], [], []
        if n >= 3 and n % 5 != 0:
            want = min(4 + n // 2, 10)
            taken = set()
            for _ in range(want * 4):
                i = random.randrange(1, PLAY_W // TILE - 1)
                j = random.randrange(1, HEIGHT // TILE - 1)
                if (i, j) in taken: continue
                r = pygame.Rect(i * TILE, j * TILE, TILE, TILE)
                if pygame.Vector2(r.center).distance_to((PLAY_W / 2, HEIGHT / 2)) < 150:
                    continue
                taken.add((i, j))
                self.crumbs.append(Crumble(r, (n, i, j)))
                if len(self.crumbs) >= want: break
        if n >= 4:
            for _ in range(2):
                for _try in range(30):
                    p = (random.uniform(80, PLAY_W - 80), random.uniform(90, HEIGHT - 90))
                    if pygame.Vector2(p).distance_to(self.player.pos) > 220 and \
                       all(pygame.Vector2(p).distance_to(t.pos) > 200 for t in self.turrets):
                        self.turrets.append(Turret(p)); break
        if n >= 7:
            for _ in range(1 + (1 if n >= 10 else 0)):
                self.sweepers.append(Sweeper())

    def enter_choose(self):
        pl = self.player
        pool = [u for u in UPGRADES if u['can'](pl) and
                ('any' in u['pool'] or pl.weapon in u['pool'])]
        picks = [(kind, item) for kind, item in
                 [(('up', u) for u in random.sample(pool, min(3, len(pool))))]]
        owned = {r['key'] for r in self.relics}
        avail = [r for r in RELICS if r['key'] not in owned]
        if avail:
            for i in range(len(picks)):
                if random.random() < 0.30:
                    picks[i] = ('relic', random.choice(avail))
                    break
        self.choices = picks
        self.card_rects = []
        self.state = 'choose'

    def pick_upgrade(self, i):
        if i >= len(self.choices): return
        kind, item = self.choices[i]
        pl = self.player
        if kind == 'up':
            item['apply'](pl)
            pl.up_counts[item['key']] = pl.up_counts.get(item['key'], 0) + 1
            pl.tags_owned |= set(item['tags'])
            self.play('upgrade')
            self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2), item['name'],
                                         COL['gold'], 18, 1.2, -16))
        else:
            item['apply'](self)
            self.relics.append(item)
            pl.tags_owned |= set(item['tags'])
            self.play('event')
            self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2),
                                         f"RELIC: {item['name']}", (255, 120, 120),
                                         16, 1.4, -16))
        self.check_syn()
        self.start_wave(self.wave + 1)
        self.state = 'play'

    def check_syn(self):
        owned = self.player.tags_owned
        for key, pair, name, desc in SYNERGIES:
            if key in self.syn: continue
            if set(pair) <= owned:
                self.syn.add(key)
                if key == 'THERMAL': self.syn_elem = 1.5
                elif key == 'FROST': self.syn_frost = True
                self.play('clear', 0.8)
                self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2 + 40),
                                             f"SYNERGY: {name} ({desc})",
                                             (150, 255, 220), 14, 1.8, -12))

    def play(self, name, vol=1.0, var=None):
        self.audio.play(name, vol, var)

    # ---- helpers -------------------------------------------------------
    def burst(self, pos, col, n, speed):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(speed * 0.25, speed)
            self.particles.append(Particle(pos, (math.cos(a) * sp, math.sin(a) * sp),
                                           random.uniform(0.25, 0.6), col,
                                           random.uniform(1.5, 3.2)))
    def ring(self, pos, col):
        self.fx_rings.append([pygame.Vector2(pos), 0.0, col])

    def inflict(self, e, chill=0.0, burn=False):
        m = self.syn_elem
        if chill: e.chill_t = max(e.chill_t, chill * m)
        if burn:
            e.burn_t = max(e.burn_t, 3.0)
            e.burn_dps = max(e.burn_dps, 9.0 * m)

    def explosion(self, pos, radius, pdmg, edmg, col,
                  harm_player=True, hitstop=0.09, quiet=False):
        self.ring(pos, col); self.burst(pos, col, 26, 330)
        self.shake = min(14, self.shake + 8)
        self.hitstop = max(self.hitstop, hitstop)
        if not quiet:
            self.play('boom'); self.audio.duck(0.4)
        for e in list(self.enemies):
            dd = e.pos.distance_to(pos)
            if dd < radius + e.st['R']:
                e.hp -= edmg; e.flash = 0.10
                if e.hp <= 0: self.kill(e)
        if harm_player and self.player.hp > 0:
            dd = self.player.pos.distance_to(pos)
            if dd < radius + Player.R:
                self.hurt_player(int(pdmg * (0.45 + 0.55 * (1 - dd / radius))), pos)

    def spawn_enemy(self, kind, pos=None):
        if pos is None:
            for _ in range(24):
                side = random.randrange(4); m = 40
                if   side == 0: p = (random.uniform(m, PLAY_W - m), m)
                elif side == 1: p = (random.uniform(m, PLAY_W - m), HEIGHT - m)
                elif side == 2: p = (m, random.uniform(m, HEIGHT - m))
                else:           p = (PLAY_W - m, random.uniform(m, HEIGHT - m))
                if pygame.Vector2(p).distance_to(self.player.pos) > 260: break
            pos = p
        e = Enemy(pos, kind, self.wave)
        self.enemies.append(e)
        self.burst(pos, TYPES[kind]['col'], 10, 130)
        self.play('spawn', 0.55)
        if kind != 'WARDEN' and self.wave >= 6:
            chance = min(0.32, 0.14 + 0.015 * self.wave)
            if random.random() < chance:
                e.affix = random.choice(('SWIFT', 'BULWARK', 'VOLATILE', 'REGEN'))
                if e.affix == 'SWIFT': e.max_speed *= 1.35
                elif e.affix == 'BULWARK':
                    e.max_hp *= 2.2; e.hp = e.max_hp; e.kb *= 0.3
                self.play('elite', 0.8)
                self.floats.append(FloatText(e.pos, e.affix + ' ELITE',
                                             (255, 255, 255), 12, 1.2, -30))

    def hurt_player(self, dmg, src):
        if self.state != 'play' or self.player.invuln > 0: return
        if self.player.shield > 0:
            self.player.shield -= 1
            self.player.invuln = 0.25
            self.burst(self.player.pos, (110, 190, 255), 8, 160)
            self.play('shield')
            return
        if self.relic_ember: dmg = int(dmg * 1.25)
        self.player.hp -= dmg; self.player.invuln = 0.85
        self.streak = 0
        self.stats['dmg'] += dmg
        self.wave_dmg += dmg
        self.dmg_log.append((pygame.time.get_ticks() / 1000.0, dmg))
        knock = self.player.pos - pygame.Vector2(src)
        if knock.length_squared() > 0:
            knock.normalize_ip(); self.player.pos += knock * 16
        self.shake = min(12, self.shake + 7)
        self.flash = 0.22; self.flash_col = (255, 60, 60)
        self.burst(self.player.pos, COL['red'], 8, 180); self.play('hurt')
        if self.player.hp <= 0:
            self.player.hp = 0; self.state = 'over'
            m = self.meta
            m['totals']['runs'] += 1
            if self.score > m['best']:
                m['best'] = int(self.score)
                m['replay'] = {'loadout': f"{self.pilot} / {self.player.weapon}",
                               'score': int(self.score), 'data': list(self.rec)[-1400:]}
            self.meta_check()
            save_meta(m)
            self.burst(self.player.pos, COL['player'], 30, 340)
            self.ring(self.player.pos, COL['player'])
            self.shake = 16; self.hitstop = 0.22
            self.audio.music(None)
            self.play('bigboom')
            self.jingle_t = 0.65
            self.audio.duck(1.2)

    def kill(self, e, cause=None):
        if e in self.enemies: self.enemies.remove(e)
        m = self.meta
        m['totals']['kills'] += 1
        if cause == 'burn': m['totals']['burn'] += 1
        if e.affix: m['totals']['elites'] += 1
        if e.kind == 'WARDEN': m['totals']['boss'] += 1
        self.streak += 1; self.streak_t = 2.4
        mult = 1 + min(12, self.streak) // 3
        if mult > self.stats['best_mult']: self.stats['best_mult'] = mult
        base = e.st['score'] + 20 * self.wave
        gained = base * mult * self.score_mult()
        if self.event and self.event['name'] == 'GOLD': gained *= 2
        if e.affix: gained *= 2
        gained = int(gained)
        self.score += gained
        self.stats['kills'][e.kind] = self.stats['kills'].get(e.kind, 0) + 1
        if self.player.leech:
            self.player.hp = min(self.player.maxhp, self.player.hp + self.player.leech)
        self.burst(e.pos, e.st['col'], 18, 230)
        self.ring(e.pos, lighten(e.st['col'], 0.3))
        self.shake = min(10, self.shake + (6 if e.kind == 'WARDEN' else 2))
        if e.kind == 'WARDEN':
            self.play('bigboom'); self.audio.duck(0.7); self.hitstop = max(self.hitstop, 0.16)
        else:
            self.play('boom')
        self.floats.append(FloatText(e.pos, f"+{gained}" +
                                     (f"  x{mult}" if mult > 1 else ""),
                                     COL['gold'] if mult > 1 else COL['text'],
                                     13 if mult > 1 else 11, 0.8))
        if e.affix:
            self.floats.append(FloatText(e.pos + (0, -16), "ELITE DOWN",
                                         (255, 255, 255), 11, 1.0, -26))
            self.hitstop = max(self.hitstop, 0.05)
            if e.affix == 'VOLATILE':
                self.explosion(e.pos, 105, 24, 55, e.st['col'])
        if self.streak >= 3:
            self.play('combo', 0.8, min(3, mult - 2))
        for b in self.bullets:
            if not b.hostile:
                d = b.pos.distance_to(e.pos)
                if 0 < d < 180:
                    b.vel += (b.pos - e.pos).normalize() * 140 * (1 - d / 180)
        drop_scale = 0.5 if self.relic_greed else 1.0
        if e.kind == 'WARDEN':
            self.burst(e.pos, COL['gold'], 40, 400)
            self.ring(e.pos, COL['gold']); self.shake = 14
            self.packs.append(Pickup(e.pos + (-20, 0), 'med'))
            self.packs.append(Pickup(e.pos + (20, 0),
                                     random.choice(('shield', 'od', 'stasis'))))
        else:
            r = random.random() * (2.0 - drop_scale)
            kind = 'med' if r < 0.14 else 'shield' if r < 0.20 else \
                   'od' if r < 0.26 else 'stasis' if r < 0.31 else None
            if e.affix and kind is None:
                kind = random.choice(('med', 'shield'))
            if kind: self.packs.append(Pickup(e.pos, kind))
            if random.random() < 0.12 * (1.0 - self.dir_care) * drop_scale:
                self.packs.append(Pickup(e.pos + (8, 8), 'med'))
        self.meta_check()

    def meta_check(self):
        m = self.meta; got = False
        for key, name, desc, pred in ACH:
            if key not in m['ach'] and pred(m, self):
                m['ach'][key] = 1; got = True
                self.toasts.append([f"ACHIEVEMENT: {name}", 3.4])
        if got:
            self.play('clear', 0.8)
            save_meta(m)

    def get_focus(self):
        alive = sorted(self.enemies, key=lambda e: e.id)
        if not alive: return None
        if self.focus_manual: return alive[self.focus_i % len(alive)]
        return min(alive, key=lambda e: e.pos.distance_to(self.player.pos))

    # ---- fuzzy director ------------------------------------------------
    def director_tick(self, dt):
        p = self.player
        now = pygame.time.get_ticks() / 1000.0
        while self.dmg_log and now - self.dmg_log[0][0] > 4.0:
            self.dmg_log.popleft()
        rec = sum(d for _, d in self.dmg_log)
        prox = 0.0
        for b in self.bullets:
            if b.hostile:
                dd = b.pos.distance_to(p.pos)
                if dd < 170: prox += 1.0 - dd / 170
        burning = sum(1 for e in self.enemies if e.burn_t > 0)   # burn feeds pressure
        pressure = min(1.0, rec / 55.0 + min(1.0, prox / 5.0) * 0.30
                       + burning * 0.04)
        flow = _clamp(0.55 * min(1.0, self.streak / 6.0) + 0.45 * self.last_clear_norm, 0, 1)
        hullv = _clamp(p.hp, 0, 140)
        vals = {'flow': flow, 'hull': hullv, 'pressure': pressure}
        out = {}; fz = None; acts = {}
        for name, sysm in DIR_SYS.items():
            o, f, a = sysm.evaluate(vals)
            out[name] = o
            if fz is None: fz = f
            acts[name] = a
        bias = 0.0 if self.relic_dire else self.dir_bias   # DIRE DEAL ignores bias
        target = _clamp(0.5 * out['power'] + 0.5 * out['spawn'] + bias, 0.03, 1.0)
        if self.relic_vamp: target = _clamp(target + 0.15, 0, 1)
        self.dir_intensity += (target - self.dir_intensity) * min(1.0, 2.2 * dt)
        i = self.dir_intensity
        self.dir_power = 0.80 + 0.45 * i + (0.18 if self.relic_thin else 0.0)
        self.dir_fire = 1.35 - 0.55 * i
        self.dir_gap = 1.50 - 0.95 * i
        self.dir_care = out['care']
        self.dir_dbg = dict(fz=fz, acts=acts, out=out, vals=(flow, hullv, pressure))
        self.dir_hist.append(i)

    # ---- bullets -------------------------------------------------------
    def _steer_missile(self, b, dt):
        b.retarget -= dt
        t = next((e for e in self.enemies
                  if e.id == b.tgt_id and e.spawn_t <= 0), None)
        if t is None or b.retarget <= 0:
            best, bt = -9.0, None
            head = math.atan2(b.vel.y, b.vel.x)
            for e in self.enemies:
                if e.spawn_t > 0 or e.id in b.hits: continue
                sc, fz, acts = target_score(e, b.pos, head)  # fuzzy target pick
                if sc > best: best, bt = sc, e
            if bt: b.tgt_id = bt.id
            b.retarget = 0.30
            t = bt
        if t is None: return None
        des = math.atan2(t.pos.y - b.pos.y, t.pos.x - b.pos.x)
        cur = math.atan2(b.vel.y, b.vel.x)
        da = (des - cur + math.pi) % (2 * math.pi) - math.pi
        mx = 4.5 * dt
        cur += _clamp(da, -mx, mx)
        sp = b.vel.length()
        b.vel = pygame.Vector2(math.cos(cur), math.sin(cur)) * sp
        if random.random() < dt * 30:
            self.particles.append(Particle(b.pos, (random.uniform(-20, 20),
                                           random.uniform(-20, 20)), 0.3, b.color, 2))
        if b.pos.distance_to(t.pos) < 24 + t.st['R']:
            return t
        return None

    def missile_boom(self, b):
        r = b.splash
        for e in list(self.enemies):
            if e.pos.distance_to(b.pos) < r + e.st['R']:
                e.hp -= b.dmg; e.flash = 0.10
                e.vel += (e.pos - b.pos).normalize() * 90 * e.kb
                if self.syn_frost: self.inflict(e, chill=1.0)
                if e.hp <= 0: self.kill(e)
        self.ring(b.pos, b.color); self.burst(b.pos, b.color, 10, 180)
        self.play('boom', 0.5)

    def move_bullets(self, dt):
        keep = []
        for b in self.bullets:
            if b.homing and not b.hostile:
                t = self._steer_missile(b, dt)
                if t is not None:
                    self.missile_boom(b)
                    continue
            b.pos += b.vel * dt; b.life -= dt
            if b.life <= 0: continue
            if not (0 <= b.pos.x <= PLAY_W and 0 <= b.pos.y <= HEIGHT): continue
            hit = False
            if b.hostile:
                if self.state == 'play' and self.player.invuln <= 0 and \
                   b.pos.distance_to(self.player.pos) < b.r + Player.R:
                    self.hurt_player(b.dmg, b.pos); hit = True
            else:
                for e in list(self.enemies):
                    if e.spawn_t > 0 or e.id in b.hits: continue
                    if b.pos.distance_to(e.pos) < b.r + e.st['R']:
                        e.hp -= b.dmg; e.flash = 0.09
                        e.vel += b.vel * b.knock * e.kb
                        self.burst(b.pos, (255, 220, 140), 4, 140)
                        self.play('hit')
                        self.stats['hits'] += 1
                        self.floats.append(FloatText(b.pos, f"{int(b.dmg)}",
                                                     (240, 240, 255), 10, 0.5, -46))
                        # ---- elemental statuses ----
                        pl = self.player
                        if pl.chill_on_hit: self.inflict(e, chill=pl.chill_on_hit)
                        if pl.burn_all or (pl.burn_chance and random.random() < pl.burn_chance):
                            self.inflict(e, burn=True)
                        if b.ignite: self.inflict(e, burn=True)
                        hit = True
                        if e.hp <= 0: self.kill(e)
                        if b.pierce > 0:
                            b.pierce -= 1; b.hits.add(e.id); hit = False
                            continue
                        break
            if not hit: keep.append(b)
        self.bullets = keep

    # ---- updates -------------------------------------------------------
    def update_fx(self, dt):
        self.particles = [p for p in self.particles if p.update(dt)]
        for r in self.fx_rings: r[1] += dt
        self.fx_rings = [r for r in self.fx_rings if r[1] < 0.28]
        self.floats = [f for f in self.floats if f.update(dt)]
        for t in list(self.toasts):
            t[1] -= dt
            if t[1] <= 0: self.toasts.remove(t)
        self.shake = max(0.0, self.shake - 26 * dt)
        self.flash = max(0.0, self.flash - dt)
        if self.jingle_t > 0:
            self.jingle_t -= dt
            if self.jingle_t <= 0: self.play('gameover')

    def update_playing(self, dt):
        self.player.update(dt, self)
        self.stats['time'] += dt
        if self._dash_was > 0 and self.player.dash_cd <= 0:
            self.play('ready', 0.7)
        self._dash_was = self.player.dash_cd
        self.freeze_t = max(0.0, self.freeze_t - dt)
        self.streak_t -= dt
        if self.streak_t <= 0: self.streak = 0
        if self.boss_warn_t > 0: self.boss_warn_t -= dt
        self.director_tick(dt)
        # flight recorder
        self.rec_t += dt
        if self.rec_t >= 0.5:
            self.rec_t = 0.0
            self.rec.append([round(self.stats['time'], 1), self.score,
                             round(self.dir_intensity, 3),
                             round(self.player.hp / self.player.maxhp, 3)])
        if self.event:
            ev = self.event
            ev['t'] -= dt; ev['banner_t'] = ev.get('banner_t', 0) - dt
            if ev['t'] <= 0:
                self.event = None
            elif ev['name'] == 'STORM':
                self.storm_t -= dt
                if self.storm_t <= 0:
                    self.storm_t = 0.5
                    side = random.randrange(4); m = 10
                    if   side == 0: pos = (random.uniform(0, PLAY_W), m)
                    elif side == 1: pos = (random.uniform(0, PLAY_W), HEIGHT - m)
                    elif side == 2: pos = (m, random.uniform(0, HEIGHT))
                    else:           pos = (PLAY_W - m, random.uniform(0, HEIGHT))
                    tgt = self.player.pos + pygame.Vector2(random.uniform(-70, 70),
                                                           random.uniform(-70, 70))
                    ang = math.atan2(tgt.y - pos[1], tgt.x - pos[0])
                    self.bullets.append(Bullet(pos, ang, 235, True, 8,
                                               (175, 190, 210), r=4))
                    self.play('eshoot', 0.25, 0)
        for c in self.crumbs: c.update(dt, self)
        for t in self.turrets: t.update(dt, self)
        for sw in self.sweepers: sw.update(dt, self)
        if self.spawn_queue:
            self.spawn_t -= dt
            if self.spawn_t <= 0:
                self.spawn_enemy(self.spawn_queue.pop(0))
                self.spawn_t = self.spawn_gap * self.dir_gap
        elif not self.enemies:
            if self.clear_t <= 0.0:
                self.clear_t = 1.6
                actual = pygame.time.get_ticks() / 1000.0 - self.wave_start
                par = 16 + 3 * self.wave
                self.last_clear_norm = _clamp(par / max(actual, 1.0), 0.0, 1.0)
                bonus = int((100 + 50 * self.wave) * self.score_mult())
                self.score += bonus
                m = self.meta
                m['totals']['waves'] = max(m['totals']['waves'], self.wave)
                if self.wave_dmg == 0:
                    m['totals']['flawless'] = m['totals'].get('flawless', 0) + 1
                self.meta_check(); save_meta(m)
                self.play('clear')
                self.floats.append(FloatText((PLAY_W / 2, HEIGHT / 2 - 80),
                                             f"WAVE CLEARED  +{bonus}",
                                             COL['green'], 18, 1.5, -14))
            else:
                self.clear_t -= dt
                if self.clear_t <= 0.0: self.enter_choose()
        for e in list(self.enemies):
            e.update(dt, self)
            if self.state != 'play': return
        self.move_bullets(dt)
        self.packs = [p for p in self.packs if p.update(dt, self)]
        for p in list(self.packs):
            if p.pos.distance_to(self.player.pos) < Pickup.R + Player.R + 4:
                if   p.kind == 'med':    self.player.hp = min(self.player.maxhp,
                                                              self.player.hp + 25)
                elif p.kind == 'shield': self.player.shield = min(3, self.player.shield + 2)
                elif p.kind == 'od':     self.player.od_t = 6.0
                else:                    self.freeze_t = 3.0
                self.play({'med': 'pickup', 'shield': 'shield',
                           'od': 'overdrive', 'stasis': 'stasis'}[p.kind])
                self.score += 50
                self.burst(p.pos, COL['green'], 10, 150)
                self.packs.remove(p)

    def update_menu(self, dt):
        self.menu_t += dt
        t = self.menu_t
        self.player.pos.x = PLAY_W / 2 + math.sin(t * 0.7) * 260
        self.player.pos.y = HEIGHT / 2 + math.sin(t * 1.13) * 180
        alive = [e for e in self.enemies if e.spawn_t <= 0]
        if alive:
            n = min(alive, key=lambda e: e.pos.distance_to(self.player.pos))
            self.player.aim = math.atan2(n.pos.y - self.player.pos.y,
                                         n.pos.x - self.player.pos.x)
        self.demo_t -= dt
        if self.demo_t <= 0 and len(self.enemies) < 4:
            self.demo_t = 2.4
            self.spawn_enemy(self.demo_kinds[len(self.enemies) % 4])
        for e in list(self.enemies):
            e.update(dt, self)
            e.demo_t -= dt
            if e.demo_t <= 0:
                self.burst(e.pos, e.st['col'], 12, 160)
                if e in self.enemies: self.enemies.remove(e)
        self.move_bullets(dt)

    # ---- events & loop -------------------------------------------------
    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if ev.type == pygame.KEYDOWN:
                k = ev.key
                if k == pygame.K_m: self.audio.toggle()
                if k == pygame.K_f: self.show_panel = not self.show_panel
                if k == pygame.K_c: self.crt = not self.crt
                if k == pygame.K_g and self.state == 'play':
                    self.panel_page = 1 - self.panel_page
                if self.state == 'menu':
                    if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.state = 'select'; self.play('ui')
                    elif k == pygame.K_l:
                        self.state = 'meta'; self.play('ui')
                elif self.state == 'meta' and k in (pygame.K_l, pygame.K_ESCAPE,
                                                    pygame.K_RETURN):
                    self.state = 'menu'; self.play('ui')
                elif self.state == 'select':
                    if pygame.K_1 <= k <= pygame.K_4:
                        i = k - pygame.K_1
                        if pilot_ok(self.meta, PILOT_ORDER[i]): self.sel_p = i; self.play('ui')
                    elif pygame.K_5 <= k <= pygame.K_8:
                        self.sel_w = k - pygame.K_5; self.play('ui')
                    elif k in (pygame.K_LEFT, pygame.K_a):
                        self.sel_p = (self.sel_p - 1) % 4; self.play('ui')
                    elif k in (pygame.K_RIGHT, pygame.K_d):
                        self.sel_p = (self.sel_p + 1) % 4; self.play('ui')
                    elif k in (pygame.K_UP, pygame.K_w):
                        self.sel_w = (self.sel_w - 1) % 4; self.play('ui')
                    elif k in (pygame.K_DOWN, pygame.K_s):
                        self.sel_w = (self.sel_w + 1) % 4; self.play('ui')
                    elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                        self.start_game()
                    elif k == pygame.K_ESCAPE:
                        self.state = 'menu'
                elif self.state in ('over',) and \
                        k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_r):
                    self.state = 'select'; self.play('ui')
                elif self.state == 'choose' and k in (pygame.K_1, pygame.K_2, pygame.K_3):
                    self.pick_upgrade(k - pygame.K_1)
                elif self.state == 'play':
                    if k == pygame.K_TAB:
                        self.focus_manual = True; self.focus_i += 1
                        self.play('ui', 0.5)
                    elif k == pygame.K_e:
                        self.player.try_dash(self)
                    elif k in (pygame.K_p, pygame.K_ESCAPE):
                        self.state = 'pause'
                    elif k == pygame.K_MINUS:
                        self.dir_bias = _clamp(self.dir_bias - 0.12, -0.30, 0.30)
                        self.play('ui', 0.5)
                    elif k in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                        self.dir_bias = _clamp(self.dir_bias + 0.12, -0.30, 0.30)
                        self.play('ui', 0.5)
                elif self.state == 'pause' and k in (pygame.K_p, pygame.K_ESCAPE, pygame.K_RETURN):
                    self.state = 'play'
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3 \
                    and self.state == 'play':
                self.player.try_dash(self)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.state == 'choose':
                    for i, (rect, _u) in enumerate(self.card_rects):
                        if rect.collidepoint(ev.pos):
                            self.pick_upgrade(i); break
                elif self.state == 'select':
                    for kind, i, rect in self.sel_rects:
                        if rect.collidepoint(ev.pos):
                            if kind == 'p':
                                if pilot_ok(self.meta, PILOT_ORDER[i]): self.sel_p = i
                            else:
                                self.sel_w = i
                            self.play('ui'); break

    def run(self):
        while True:
            raw = min(self.clock.tick(FPS) / 1000.0, 0.05)
            self.handle_events()
            self.audio.update(raw)
            k = pygame.key.get_pressed()
            slow = self.state == 'play' and (k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT])
            self.time_scale = 0.32 if slow else 1.0
            dt = raw * self.time_scale
            if self.state == 'play':
                gdt = dt
                if self.hitstop > 0:
                    self.hitstop -= raw
                    gdt = dt * 0.05
                self.update_playing(gdt); self.update_fx(raw)
            elif self.state in ('menu', 'select', 'meta'):
                self.update_menu(raw); self.update_fx(raw)
            else:
                self.update_fx(raw)
            self.draw()

    # ---- drawing -------------------------------------------------------
    def draw_world(self):
        w = self.world
        w.fill(COL['bg'])
        for gx in range(0, PLAY_W, 42): pygame.draw.line(w, COL['grid'], (gx, 0), (gx, HEIGHT))
        for gy in range(0, HEIGHT, 42): pygame.draw.line(w, COL['grid'], (0, gy), (PLAY_W, gy))
        pygame.draw.rect(w, COL['border'], (0, 0, PLAY_W, HEIGHT), 2)
        frozen = self.freeze_t > 0
        for c in self.crumbs: c.draw(w)
        for pk in self.packs: pk.draw(w)
        for t in self.turrets: t.draw(w)
        for b in self.bullets:
            if b.homing and not b.hostile:
                a = math.atan2(b.vel.y, b.vel.x)
                tip = b.pos + pygame.Vector2(math.cos(a), math.sin(a)) * 7
                l = b.pos - pygame.Vector2(math.cos(a), math.sin(a)) * 6
                per = pygame.Vector2(-math.sin(a), math.cos(a)) * 3
                pygame.draw.polygon(w, b.color, [tip, l + per, l - per])
            elif self.player.weapon == 'RAIL' and not b.hostile and b.r > 4:
                pygame.draw.line(w, b.color, b.pos - b.vel * 0.03, b.pos, 3)
                pygame.draw.circle(w, (255, 255, 255), b.pos, 2)
            else:
                pygame.draw.circle(w, b.color, b.pos, int(b.r))
                if not b.hostile:
                    pygame.draw.line(w, b.color, b.pos - b.vel * 0.02, b.pos, 2)
        focus = self.get_focus()
        for e in self.enemies: e.draw(w, frozen)
        if focus is not None and focus.want.length_squared() > 4 and focus.spawn_t <= 0:
            v = focus.want
            L = min(46, v.length() * 0.14)
            tip = focus.pos + v.normalize() * L
            pygame.draw.line(w, COL['gold'], focus.pos, tip, 2)
            d = v.normalize()
            per = pygame.Vector2(-d.y, d.x)
            pygame.draw.polygon(w, COL['gold'],
                                [tip, tip - d * 8 + per * 4, tip - d * 8 - per * 4])
            r = focus.st['R'] + 9
            for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                cx, cy = focus.pos.x + dx * r, focus.pos.y + dy * r
                pygame.draw.line(w, (240, 245, 255), (cx, cy), (cx - dx * 7, cy), 1)
                pygame.draw.line(w, (240, 245, 255), (cx, cy), (cx, cy - dy * 7), 1)
        if self.state in ('play', 'pause', 'choose', 'over') and self.player.hp > 0:
            self.player.draw(w)
        for p in self.particles: p.draw(w)
        for pos, t, col in self.fx_rings:
            kk = 1 - t / 0.28
            pygame.draw.circle(w, dim(col, max(0.0, kk * 0.9)), pos, int(6 + t * 380), 3)
        for sw in self.sweepers: sw.draw(w)
        for f in self.floats:
            surf = self.f_tiny if f.size <= 12 else self.f_small if f.size <= 18 else self.f_med
            img = surf.render(f.txt, True, dim(f.col, min(1.0, f.life / f.max * 1.4)))
            w.blit(img, (f.pos.x - img.get_width() / 2, f.pos.y - img.get_height() / 2))
        if self.event and self.event['name'] == 'FOG':
            fog = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
            fog.fill((8, 10, 16, 170))
            w.blit(fog, (0, 0))
            R = 175
            for b in self.bullets:
                if b.pos.distance_to(self.player.pos) < R + 40:
                    pygame.draw.circle(w, b.color, b.pos, int(b.r))
            for e in self.enemies:
                if e.pos.distance_to(self.player.pos) < R + e.st['R']:
                    e.draw(w, frozen)
            if self.player.hp > 0: self.player.draw(w)
            for p in self.particles:
                if p.pos.distance_to(self.player.pos) < R: p.draw(w)
            pygame.draw.circle(w, (120, 150, 190), self.player.pos, R, 1)
            pygame.draw.circle(w, (70, 90, 120), self.player.pos, R - 12, 1)

    def draw_hud(self):
        s = self.screen
        s.blit(self.f_med.render(f"SCORE {self.score}", True, COL['gold']), (16, 10))
        s.blit(self.f_med.render(f"BEST {self.meta['best']}", True, COL['dim']), (240, 14))
        s.blit(self.f_med.render(f"WAVE {max(1, self.wave)}", True, COL['text']), (380, 10))
        n = len(self.enemies) + len(self.spawn_queue)
        s.blit(self.f_med.render(f"DRONES {n}", True, COL['red'] if n else COL['dim']),
               (PLAY_W - 170, 10))
        i = self.dir_intensity
        word = 'EASING' if i < 0.35 else 'STEADY' if i < 0.65 else 'CRANKING'
        dcol = lerp(COL['green'], COL['red'], i)
        s.blit(self.f_tiny.render(f"DIR {word}", True, dcol), (PLAY_W - 170, 32))
        br = pygame.Rect(PLAY_W - 100, 34, 84, 6)
        pygame.draw.rect(s, (36, 42, 56), br)
        pygame.draw.rect(s, dcol, (br.x, br.y, int(br.w * i), br.h))
        pygame.draw.rect(s, COL['edge'], br, 1)
        if self.event:
            ev = self.event
            ttxt = f"  {int(ev['t'])}s" if ev['name'] == 'STORM' else ""
            s.blit(self.f_tiny.render(f"[{ev['name']}{ttxt}]", True, COL['gold']),
                   (PLAY_W - 170, 44))
        if self.audio.muted:
            s.blit(self.f_tiny.render("MUTED (M)", True, COL['red']), (PLAY_W - 170, 70))
        s.blit(self.f_small.render("HULL", True, COL['dim']), (16, 42))
        r = pygame.Rect(60, 40, 190, 14)
        pygame.draw.rect(s, (36, 42, 56), r)
        frac = self.player.hp / self.player.maxhp
        pygame.draw.rect(s, lerp(COL['red'], COL['green'], frac),
                         (r.x, r.y, max(0, int(r.w * frac)), r.h))
        pygame.draw.rect(s, COL['edge'], r, 1)
        s.blit(self.f_small.render(f"{int(self.player.hp)}/{self.player.maxhp}",
                                   True, COL['text']), (r.right + 10, r.y - 1))
        for i2 in range(self.player.shield):
            pygame.draw.rect(s, (110, 190, 255), (r.x + i2 * 12, r.bottom + 4, 9, 5))
        s.blit(self.f_tiny.render(
            f"{self.pilot} / {self.player.weapon}"
            + (f" / relics {len(self.relics)}" if self.relics else ""),
            True, COL['dim']), (16, 72))
        dfrac = 1.0 - _clamp(self.player.dash_cd / (2.6 * self.player.dash_mult), 0, 1)
        s.blit(self.f_small.render("DASH", True, COL['dim']), (16, 58))
        dr = pygame.Rect(60, 58, 90, 7)
        pygame.draw.rect(s, (36, 42, 56), dr)
        pygame.draw.rect(s, (140, 220, 255) if dfrac >= 1 else (70, 100, 130),
                         (dr.x, dr.y, int(dr.w * dfrac), dr.h))
        pygame.draw.rect(s, COL['edge'], dr, 1)
        if self.player.od_t > 0:
            o = pygame.Rect(160, 58, 90, 7)
            pygame.draw.rect(s, (36, 42, 56), o)
            pygame.draw.rect(s, COL['gold'], (o.x, o.y, int(o.w * self.player.od_t / 6), 7))
        if self.streak >= 3:
            mult = 1 + min(12, self.streak) // 3
            s.blit(self.f_med.render(f"COMBO x{mult}", True, COL['gold']),
                   (PLAY_W / 2 - 60, 10))
            bar = pygame.Rect(PLAY_W / 2 - 60, 36, 120, 5)
            pygame.draw.rect(s, (36, 42, 56), bar)
            pygame.draw.rect(s, COL['gold'], (bar.x, bar.y,
                                              int(bar.w * self.streak_t / 2.4), 5))
        boss = next((e for e in self.enemies if e.kind == 'WARDEN'), None)
        if boss:
            bw = 300
            br = pygame.Rect(PLAY_W / 2 - bw // 2, 26, bw, 10)
            pygame.draw.rect(s, (36, 42, 56), br)
            pygame.draw.rect(s, TYPES['WARDEN']['col'],
                             (br.x, br.y, int(br.w * boss.hp / boss.max_hp), br.h))
            pygame.draw.rect(s, COL['edge'], br, 1)
            lbl = "WARDEN" if boss.phase == 1 else "WARDEN: PHASE II"
            s.blit(self.f_small.render(lbl, True,
                                       lighten(TYPES['WARDEN']['col']) if boss.phase == 2
                                       else TYPES['WARDEN']['col']),
                   (PLAY_W / 2 - 40, 38))
        if self.boss_warn_t > 0 and int(self.boss_warn_t * 4) % 2 == 0:
            t = self.f_med.render("!! WARDEN INBOUND !!", True, COL['red'])
            s.blit(t, (PLAY_W / 2 - t.get_width() / 2, HEIGHT / 2 - 90))
        if self.time_scale < 1.0:
            s.blit(self.f_small.render("SLOW-MO 0.3x", True, COL['gold']),
                   (PLAY_W - 170, 58))
        s.blit(self.f_tiny.render(
            "hold fire=charge(PULSE)  E dash  TAB drone  G page  L meta  -/= bias  C crt  M mute",
            True, COL['dim']), (16, HEIGHT - 16))
        mx, my = pygame.mouse.get_pos()
        pygame.draw.circle(s, (200, 230, 255), (mx, my), 8, 1)
        for a in range(4):
            dx, dy = math.cos(a * math.pi / 2), math.sin(a * math.pi / 2)
            pygame.draw.line(s, (200, 230, 255), (mx + dx * 10, my + dy * 10),
                             (mx + dx * 15, my + dy * 15), 1)

    def _bar(self, s, x, y, w, label, val, lo, hi, color):
        h = 11; trough = pygame.Rect(x + 78, y, w - 78 - 42, h)
        pygame.draw.rect(s, (26, 32, 45), trough)
        vx = trough.left + (_clamp(val, lo, hi) - lo) / (hi - lo) * trough.w
        zx = trough.left + (0.0 - lo) / (hi - lo) * trough.w
        pygame.draw.rect(s, color, (min(vx, zx), trough.y, max(2.0, abs(vx - zx)), h))
        if lo < 0: pygame.draw.line(s, COL['edge'], (zx, trough.y), (zx, trough.bottom), 1)
        pygame.draw.rect(s, COL['edge'], trough, 1)
        s.blit(self.f_small.render(label, True, COL['text']), (x + 2, y))
        s.blit(self.f_small.render(f"{val:+.2f}" if lo < 0 else f"{val:.2f}", True, color),
               (x + w - 40, y))

    def _rule_rows(self, s, acts, y, W, max_rows, L):
        rows = []
        for name, lst in acts.items():
            for r, ss in lst: rows.append((ss, name, r))
        rows.sort(key=lambda t: -t[0])
        for ss, name, r in rows[:max_rows]:
            row = pygame.Rect(L, y, W, 17)
            pygame.draw.rect(s, lerp((18, 23, 33), COL['gold'], 0.08 + 0.72 * min(1, ss)), row)
            tcol = SYS_COL.get(name, DIR_COL.get(name, COL['text']))
            pygame.draw.rect(s, tcol, (row.x + 4, y + 5, 7, 7))
            dark = ss > 0.5
            tc = (25, 22, 15) if dark else COL['text']
            s.blit(self.f_tiny.render(r.label[:34], True, tc), (row.x + 16, y + 3))
            zt = f"z={r.z:+.2f}" if isinstance(r.z, (int, float)) else f"-> {r.z}"
            s.blit(self.f_tiny.render(zt, True, (25, 22, 15) if dark else COL['dim']),
                   (row.x + 186, y + 3))
            s.blit(self.f_tiny.render(f"s={ss:.2f}", True,
                                      (25, 22, 15) if dark else COL['gold']),
                   (row.right - 44, y + 3))
            y += 19
        return y

    def draw_panel(self):
        s = self.screen
        x = PANEL_X; L = x + 10; W = WIDTH - L - 10
        pygame.draw.rect(s, COL['panel'], (x - 6, 0, WIDTH - x + 6, HEIGHT))
        pygame.draw.line(s, COL['edge'], (x - 6, 0), (x - 6, HEIGHT), 1)
        if self.panel_page == 1:
            self._panel_director(s, L, W); return
        s.blit(self.f_med.render("FUZZY BRAIN", True, COL['gold']), (L, 8))
        e = self.get_focus()
        if e is None or e.debug is None:
            s.blit(self.f_small.render("no drones active - panel idles", True, COL['dim']),
                   (L + 4, 60))
            s.blit(self.f_tiny.render("G director page  F hide  M mute", True, COL['dim']),
                   (L + 6, HEIGHT - 16))
            return
        tag = "MAMDANI" if e.kind.startswith('WARDEN') else "SUGENO"
        if e.kind == 'WARDEN': tag += f" PHASE {e.phase}"
        s.blit(self.f_small.render(f"{e.kind}  #{e.id}   [{tag}]", True, e.st['col']),
               (L, 32))
        stx = L + 240
        if e.chill_t > 0:
            s.blit(self.f_tiny.render("CHILLED 20Hz", True, (150, 225, 255)), (stx, 34))
        if e.burn_t > 0:
            s.blit(self.f_tiny.render("BURNING", True, (255, 150, 60)), (stx, 44))
        d, hp, dg, wt, pk, pr = e.inputs
        fz = e.debug['fz']; acts = e.debug['acts']; out = e.debug['out']
        y = 50
        for var, val in zip(VARS, (d, hp, dg, wt, pk, pr)):
            draw_chart(s, pygame.Rect(L, y, W, 60), var, val, fz[var.name], self.f_tiny)
            y += 66
        total = sum(len(a) for a in acts.values())
        s.blit(self.f_small.render(f"RULES  min-AND  ({total} total)", True, COL['dim']),
               (L, y)); y += 16
        y = self._rule_rows(s, acts, y, W, 7, L)
        y += 4
        s.blit(self.f_small.render("OUTPUTS  crisp (defuzzified)", True, COL['dim']),
               (L, y)); y += 15
        for name, lo, hi in (('approach', -1, 1), ('strafe', -1, 1), ('fire', 0, 1)):
            self._bar(s, L, y, W, name, out[name], lo, hi, SYS_COL[name]); y += 21
        if e.kind.startswith('WARDEN') and e.debug.get('mags'):
            y += 4
            pts, ovar, crisp = e.debug['mags']
            draw_mamdani(s, pygame.Rect(L, y, W, 88), pts, ovar, crisp, self.f_tiny)
        else:
            draw_telemetry(s, pygame.Rect(L, min(y + 4, HEIGHT - 64), W, 60),
                           e.hist, self.f_tiny)

    def _panel_director(self, s, L, W):
        s.blit(self.f_med.render("FUZZY DIRECTOR", True, COL['gold']), (L, 8))
        s.blit(self.f_tiny.render("dynamic difficulty - it plays you, you play it",
                                  True, COL['dim']), (L, 34))
        if self.dir_dbg is None:
            s.blit(self.f_small.render("starts observing when the run begins", True,
                                       COL['dim']), (L + 4, 60))
            return
        fz = self.dir_dbg['fz']; acts = self.dir_dbg['acts']
        out = self.dir_dbg['out']; vals = self.dir_dbg['vals']
        y = 50
        for var, val in zip(DIR_VARS, vals):
            draw_chart(s, pygame.Rect(L, y, W, 62), var, val, fz[var.name], self.f_tiny)
            y += 68
        s.blit(self.f_small.render("RULES  min-AND", True, COL['dim']), (L, y)); y += 16
        y = self._rule_rows(s, acts, y, W, 8, L)
        y += 4
        s.blit(self.f_small.render("OUTPUTS", True, COL['dim']), (L, y)); y += 15
        for name in ('spawn', 'power', 'care'):
            self._bar(s, L, y, W, name, out[name], 0, 1, DIR_COL[name]); y += 21
        y += 2
        s.blit(self.f_tiny.render(
            f"gap x{self.dir_gap:.2f}  speed x{self.dir_power:.2f}  "
            f"cooldown x{self.dir_fire:.2f}  loot {self.dir_care:.2f}",
            True, COL['text']), (L, y)); y += 16
        i = self.dir_intensity
        word = 'EASING' if i < 0.35 else 'STEADY' if i < 0.65 else 'CRANKING'
        self._bar(s, L, y, W, f"INTENSITY {word}", i, 0, 1,
                  lerp(COL['green'], COL['red'], i)); y += 20
        draw_ihist(s, pygame.Rect(L, y, W, 58), self.dir_hist, self.f_tiny)
        y += 62
        bias_note = " (IGNORED - DIRE DEAL)" if self.relic_dire else ""
        s.blit(self.f_tiny.render(f"bias {self.dir_bias:+.2f}{bias_note}  [-] calmer  [+] meaner",
                                  True, COL['gold']), (L, y))

    def draw_cards(self):
        s = self.screen
        ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        ov.fill((6, 8, 14, 200)); s.blit(ov, (0, 0))
        self._center(s, self.f_med, "WAVE CLEARED - CHOOSE", COL['gold'], HEIGHT / 2 - 190)
        cw, ch, gap = 230, 250, 24
        x0 = PLAY_W / 2 - (cw * 3 + gap * 2) / 2
        y0 = HEIGHT / 2 - 120
        mx, my = pygame.mouse.get_pos()
        self.card_rects = []
        for i, (kind, item) in enumerate(self.choices):
            r = pygame.Rect(int(x0 + i * (cw + gap)), int(y0), cw, ch)
            hover = r.collidepoint((mx, my))
            self.card_rects.append((r, item))
            relic = kind == 'relic'
            pygame.draw.rect(s, (32, 22, 26) if relic else (24, 30, 44), r)
            bcol = (255, 100, 100) if relic else (COL['gold'] if hover else COL['edge'])
            pygame.draw.rect(s, bcol, r, 2)
            s.blit(self.f_med.render(f"[{i + 1}]", True,
                                     (255, 120, 120) if relic else COL['gold']),
                   (r.x + 10, r.y + 10))
            if relic:
                s.blit(self.f_tiny.render("RELIC / CURSE", True, (255, 120, 120)),
                       (r.right - 86, r.y + 18))
            elif self.player.up_counts.get(item['key']):
                s.blit(self.f_small.render("LV 2", True, COL['green']),
                       (r.right - 40, r.y + 14))
            title = self.f_small.render(item['name'], True, COL['text'])
            s.blit(title, (r.centerx - title.get_width() / 2, r.y + 52))
            yy = r.y + 80
            for line in item['desc']:
                img = self.f_tiny.render(line, True, COL['dim'])
                s.blit(img, (r.centerx - img.get_width() / 2, yy)); yy += 15
            tags = ",".join(item['tags'])
            s.blit(self.f_tiny.render("tags: " + tags, True, (150, 255, 220)),
                   (r.centerx - 60, r.bottom - 40))
            if hover and not relic:
                s.blit(self.f_tiny.render("click or press number", True, COL['gold']),
                       (r.centerx - 62, r.bottom - 24))

    def draw_select(self):
        s = self.screen
        ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        ov.fill((8, 10, 17, 205)); s.blit(ov, (0, 0))
        self._center(s, self.f_big, "LOADOUT", COL['gold'], 40)
        self._center(s, self.f_small,
                     "1-4 pilot  5-8 weapon  arrows navigate  click  ENTER launch",
                     COL['dim'], 96)
        mx, my = pygame.mouse.get_pos()
        self.sel_rects = []
        s.blit(self.f_med.render("PILOT", True, COL['text']), (PLAY_W / 2 - 320, 130))
        cw, chh, gap = 210, 130, 16
        x0 = PLAY_W / 2 - (cw * 4 + gap * 3) / 2
        for i, pk in enumerate(PILOT_ORDER):
            r = pygame.Rect(int(x0 + i * (cw + gap)), 160, cw, chh)
            ok = pilot_ok(self.meta, pk)
            sel = (self.sel_p == i)
            self.sel_rects.append(('p', i, r))
            pygame.draw.rect(s, (24, 30, 44) if ok else (16, 18, 24), r)
            pygame.draw.rect(s, COL['gold'] if sel and ok else COL['edge'], r, 2)
            col = PILOTS[pk]['col'] if ok else (90, 95, 110)
            s.blit(self.f_small.render(pk if ok else pk + " [LOCKED]", True, col),
                   (r.x + 10, r.y + 10))
            yy = r.y + 34
            for line in PILOTS[pk]['blurb'].split(', '):
                s.blit(self.f_tiny.render(line, True, COL['dim'] if ok else (80, 85, 100)),
                       (r.x + 10, yy)); yy += 14
            if not ok:
                cond = {'NOVA': 'unlock: combo x5', 'BULWARK': 'unlock: wave 8',
                        'GHOST': 'unlock: 25 burn kills'}[pk]
                s.blit(self.f_tiny.render(cond, True, (150, 120, 90)), (r.x + 10, r.bottom - 20))
        s.blit(self.f_med.render("WEAPON", True, COL['text']), (PLAY_W / 2 - 320, 320))
        for i, wk in enumerate(WEAPON_ORDER):
            r = pygame.Rect(int(x0 + i * (cw + gap)), 350, cw, 150)
            wd = WEAPONS[wk]
            sel = (self.sel_w == i)
            self.sel_rects.append(('w', i, r))
            pygame.draw.rect(s, (24, 30, 44), r)
            pygame.draw.rect(s, COL['gold'] if sel else COL['edge'], r, 2)
            s.blit(self.f_small.render(wd['name'], True, wd['col']), (r.x + 10, r.y + 10))
            yy = r.y + 34
            for line in wd['blurb']:
                s.blit(self.f_tiny.render(line, True, COL['dim']), (r.x + 10, yy)); yy += 14
            s.blit(self.f_tiny.render(f"pool: {wd['tag']} upgrades", True, (150, 255, 220)),
                   (r.x + 10, r.bottom - 20))
            if sel:
                pygame.draw.polygon(s, COL['gold'],
                                    [(r.x - 12, r.centery - 6), (r.x - 12, r.centery + 6),
                                     (r.x - 4, r.centery)])
        self._center(s, self.f_med, "PRESS ENTER TO LAUNCH", COL['green'], HEIGHT - 70)

    def draw_meta(self):
        s = self.screen
        ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        ov.fill((8, 10, 17, 215)); s.blit(ov, (0, 0))
        m = self.meta
        self._center(s, self.f_big, "META TERMINAL", COL['gold'], 30)
        t = m['totals']
        s.blit(self.f_small.render(
            f"best {m['best']}   runs {t['runs']}   kills {t['kills']}   "
            f"waves {t['waves']}   bosses {t['boss']}   burn kills {t['burn']}   "
            f"turrets {t['turret']}   elites {t['elites']}", True, COL['text']),
            (PLAY_W / 2 - 380, 92))
        s.blit(self.f_med.render("ACHIEVEMENTS", True, COL['text']), (60, 128))
        y = 158
        for key, name, desc, _p in ACH:
            done = key in m['ach']
            mark = "[x]" if done else "[ ]"
            s.blit(self.f_small.render(f"{mark} {name}", True,
                                       COL['green'] if done else COL['dim']), (60, y))
            s.blit(self.f_tiny.render(desc, True, (90, 100, 120)), (260, y + 2))
            y += 20
        s.blit(self.f_med.render("BEST RUN - FLIGHT RECORDER", True, COL['text']),
               (60, y + 16))
        rect = pygame.Rect(60, y + 44, 460, 130)
        pygame.draw.rect(s, (14, 18, 26), rect)
        pygame.draw.rect(s, COL['edge'], rect, 1)
        rp = m.get('replay')
        if rp and len(rp['data']) >= 2:
            data = rp['data']
            n = len(data)
            maxsc = max(d[1] for d in data) or 1
            pts = [(rect.left + (rect.w - 6) * i / (n - 1) + 3,
                    rect.bottom - 4 - (d[1] / maxsc) * (rect.h - 18))
                   for i, d in enumerate(data)]
            pygame.draw.lines(s, COL['gold'], False, pts, 1)
            for idx, col in ((2, COL['green']), (3, (120, 200, 255))):
                pts2 = [(rect.left + (rect.w - 6) * i / (n - 1) + 3,
                         rect.bottom - 4 - d[idx] * (rect.h - 18))
                        for i, d in enumerate(data)]
                pygame.draw.lines(s, col, False, pts2, 1)
            s.blit(self.f_tiny.render(f"{rp['loadout']}   final {rp['score']}   "
                                      "gold score / green intensity / blue hull",
                                      True, COL['dim']), (rect.left + 4, rect.top + 2))
        else:
            s.blit(self.f_small.render("no best run recorded yet", True, COL['dim']),
                   (rect.left + 8, rect.centery))
        s.blit(self.f_med.render("PILOTS", True, COL['text']), (580, y + 16))
        yy = y + 46
        for pk in PILOT_ORDER:
            ok = pilot_ok(m, pk)
            s.blit(self.f_small.render(f"{pk} - {PILOTS[pk]['blurb']}", True,
                                       PILOTS[pk]['col'] if ok else (90, 95, 110)), (580, yy))
            yy += 19
        if int(pygame.time.get_ticks() / 500) % 2 == 0:
            self._center(s, self.f_small, "L / ESC back", COL['green'], HEIGHT - 40)

    def _center(self, s, f, txt, col, y):
        img = f.render(txt, True, col)
        s.blit(img, (PLAY_W / 2 - img.get_width() / 2, y))

    def draw_menu(self):
        s = self.screen
        ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        ov.fill((8, 10, 17, 150)); s.blit(ov, (0, 0))
        self._center(s, self.f_big, "FUZZY BOT ARENA", COL['gold'], 80)
        self._center(s, self.f_base,
                     "six fuzzy engines: drone brains, warden phases, homing target scoring, and the director",
                     COL['text'], 140)
        lines = ["GRUNT/RUSHER/SNIPER/PHANTOM/BOMBER sugeno brains | WARDEN mamdani + phase II",
                 "homing missiles & captured turrets pick targets with a fuzzy scorer",
                 "chill lags their brains to 20Hz | burn feeds the director's pressure",
                 "4 weapons x pilot loadouts | relics, curses & synergy tags",
                 "laser sweepers, crumbling tiles, capturable turrets | L = meta terminal"]
        y = 180
        for L2 in lines:
            self._center(s, self.f_small, L2, COL['dim'], y); y += 19
        y += 4
        for k, v in (("ENTER", "loadout select"), ("L", "meta / achievements"),
                     ("M", "mute"), ("F / C", "panel / crt")):
            s.blit(self.f_small.render(f"{k:<10}", True, COL['gold']),
                   (PLAY_W / 2 - 120, y))
            s.blit(self.f_small.render(v, True, COL['text']), (PLAY_W / 2 - 20, y)); y += 17
        if int(pygame.time.get_ticks() / 500) % 2 == 0:
            self._center(s, self.f_med, "PRESS  ENTER", COL['green'], HEIGHT - 60)

    def draw_over(self):
        s = self.screen
        ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
        ov.fill((10, 6, 8, 195)); s.blit(ov, (0, 0))
        self._center(s, self.f_big, "SIGNAL LOST", COL['red'], 130)
        self._center(s, self.f_med, f"score {self.score}", COL['gold'], 196)
        self._center(s, self.f_base,
                     f"{self.pilot} / {self.player.weapon}"
                     + (f" / {len(self.relics)} relics" if self.relics else "")
                     + f"  -  wave {max(1, self.wave)}", COL['text'], 232)
        if self.score >= self.meta['best'] and self.score > 0:
            self._center(s, self.f_small, "NEW BEST - FLIGHT RECORDER SAVED", COL['green'], 258)
        st = self.stats
        acc = 100.0 * st['hits'] / st['fired'] if st['fired'] else 0.0
        tot = sum(st['kills'].values())
        mm, ss = int(st['time'] // 60), int(st['time'] % 60)
        killstr = "  ".join(f"{k.lower()[:4]}:{v}" for k, v in sorted(st['kills'].items()))
        rows = [f"accuracy {acc:.0f}%   shots {st['fired']}   hits {st['hits']}",
                f"kills {tot}   {killstr}",
                f"damage taken {st['dmg']}   best combo x{st['best_mult']}",
                f"survived {mm}:{ss:02d}"]
        y = 288
        for L2 in rows:
            self._center(s, self.f_small, L2, COL['dim'], y); y += 19
        if int(pygame.time.get_ticks() / 500) % 2 == 0:
            self._center(s, self.f_med, "ENTER / R - loadout", COL['green'], HEIGHT - 80)

    def draw(self):
        self.draw_world()
        s = self.screen
        s.fill(COL['panel'])
        ox = oy = 0
        if self.shake > 0.3:
            ox = random.uniform(-1, 1) * self.shake
            oy = random.uniform(-1, 1) * self.shake
        s.blit(self.world, (int(ox), int(oy)))
        if self.crt:
            s.blit(self.scan, (0, 0))
        if self.flash > 0:
            fl = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
            fl.fill((*self.flash_col, int(90 * self.flash / 0.22)))
            s.blit(fl, (0, 0))
        if self.state in ('play', 'pause', 'choose'): self.draw_hud()
        if self.player.hp < 30 and self.player.hp > 0 and self.state == 'play':
            pulse = 12 + 10 * math.sin(pygame.time.get_ticks() * 0.008)
            pygame.draw.rect(s, COL['red'], (0, 0, PLAY_W, HEIGHT), int(pulse // 4) or 1)
        if self.show_panel and self.state in ('play', 'pause', 'choose'):
            self.draw_panel()
        for i, (txt, t) in enumerate(self.toasts):
            img = self.f_small.render(txt, True, COL['gold'])
            s.blit(img, (PLAY_W / 2 - img.get_width() / 2, 66 + i * 20))
        if self.state == 'menu': self.draw_menu()
        elif self.state == 'select': self.draw_select()
        elif self.state == 'meta': self.draw_meta()
        elif self.state == 'choose': self.draw_cards()
        elif self.state == 'pause':
            ov = pygame.Surface((PLAY_W, HEIGHT), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 140)); s.blit(ov, (0, 0))
            self._center(s, self.f_med, "PAUSED  -  P to resume", COL['text'], HEIGHT / 2 - 70)
            self._center(s, self.f_small, "F panel | G drone/director | TAB drone | M mute",
                         COL['dim'], HEIGHT / 2 - 30)
            self._center(s, self.f_small, "-/= argue with the director | C scanlines",
                         COL['dim'], HEIGHT / 2 - 10)
        pygame.display.flip()

if __name__ == '__main__':
    Game().run()