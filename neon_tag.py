"""
╔══════════════════════════════════════════════════════════════════════╗
║                       N E O N   T A G  v2                            ║
║         Two-Player Top-Down Tag  ·  pygame-ce  ·  Online Play          ║
╠══════════════════════════════════════════════════════════════════════╣
║  LOCAL PLAY                                                          ║
║    P1 (Cyan)   :  W / A / S / D                                      ║
║    P2 (Orange) :  Arrow Keys                                         ║
║    1 – 5       :  Switch map                                         ║
║    R           :  Restart round / match                              ║
║    ESC         :  Menu                                               ║
║                                                                      ║
║  ONLINE PLAY   (requires  pip install websockets)                    ║
║    Host a room → share the 4-letter code with your friend            ║
║    Friend types the code to join instantly                           ║
║    Server: run neon_tag_server.py (free deploy on Railway/Render)    ║
║                                                                      ║
║  HOT POTATO RULES                                                    ║
║    ▸ NOT "IT" : +1.0 pt / s                                          ║
║    ▸ IS  "IT" : −0.8 pt / s  (score never goes below 0)              ║
║    ▸ Round timer: 90 s  →  higher score wins the round               ║
║    ▸ Match: Best of 3 rounds  (first to 2 round-wins)                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ═════════════════════════════════════════════════════════════════════════════
#  IMPORTS
# ═════════════════════════════════════════════════════════════════════════════

import sys, math, random, asyncio, json, time as _time
from typing import Optional, List, Dict, Any

import pygame
from pygame.math import Vector2

# Optional: numpy for sound synthesis
try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

# Optional: websockets for online play
try:
    import websockets                          # type: ignore
    _ONLINE_OK = True
except ImportError:
    _ONLINE_OK = False


# ═════════════════════════════════════════════════════════════════════════════
#  PYGAME INIT
# ═════════════════════════════════════════════════════════════════════════════

pygame.init()
try:
    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
    _AUDIO = True
except Exception:
    _AUDIO = False

WIN_W, WIN_H = 960, 680
HUD_H        = 68
PF_X, PF_Y   = 0, HUD_H
PF_W, PF_H   = WIN_W, WIN_H - HUD_H   # 960 × 612

screen = pygame.display.set_mode((WIN_W, WIN_H))
pygame.display.set_caption("NEON TAG")
clock  = pygame.time.Clock()
FPS    = 60


# ═════════════════════════════════════════════════════════════════════════════
#  FONTS
# ═════════════════════════════════════════════════════════════════════════════

def _mkfont(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("Consolas", "Courier New", "DejaVu Sans Mono",
                 "Liberation Mono", None):
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, size)

F_HUGE = _mkfont(80, True)
F_XL   = _mkfont(58, True)
F_LG   = _mkfont(34, True)
F_MD   = _mkfont(22, True)
F_SM   = _mkfont(15)
F_XS   = _mkfont(13)


# ═════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ═════════════════════════════════════════════════════════════════════════════

BG         = (9,   7,  19)
HUD_BG     = (12,  9,  24)
HUD_LINE   = (50,  40,  88)
WALL_F     = (38,  30,  64)
WALL_HI    = (78,  62, 126)
WALL_SH    = (18,  14,  32)
TILE_A     = (11,   9,  22)
TILE_B     = (14,  11,  27)

P1C        = ( 60, 188, 255)   # cyan-blue
P2C        = (255, 115,  36)   # warm orange

IT_RING    = (255,  42,  62)
SAFE_C     = ( 72, 228, 124)
FLASH_C    = (255, 245, 110)
TAG_C      = (255,  60,  80)

TXT_HI     = (218, 196, 255)
TXT_P1     = ( 88, 202, 255)
TXT_P2     = (255, 146,  72)
TXT_IT     = (255,  62,  72)
TXT_WIN    = (255, 218,  50)
TXT_DIM    = ( 86,  70, 138)
TXT_OK     = ( 80, 228, 128)
TXT_ERR    = (255,  72,  72)


# ═════════════════════════════════════════════════════════════════════════════
#  GAME CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

PSZ        = 26      # player square px
SPD_MAX    = 235     # max speed px/s
ACCEL      = 980     # acceleration px/s²
DECEL      = 740     # friction px/s²
GRACE      = 1.8     # immunity seconds after being tagged
START_GR   = 1.6     # prey immunity at round-start

ROUND_TIME = 90.0    # seconds per round
WIN_ROUNDS = 2       # rounds needed to win the match
SCORE_RATE = 1.0     # pts/s while NOT IT
BURN_RATE  = 0.8     # pts/s lost while IS IT (hot potato)
TILE_SZ    = 38
WT         = 20      # default wall thickness


# ═════════════════════════════════════════════════════════════════════════════
#  SOUND MANAGER  (numpy synthesis – graceful no-op if unavailable)
# ═════════════════════════════════════════════════════════════════════════════

class SoundManager:
    SR = 22050

    def __init__(self) -> None:
        self._sounds: Dict[str, Any] = {}
        self.enabled = _AUDIO and _NUMPY
        if self.enabled:
            self._build()

    # ── synthesis helpers ─────────────────────────────────────────────────────

    def _wave(self, freq: float, dur: float, shape: str = "sine",
              vol: float = 0.55, attack: float = 0.008, release: float = 0.06,
              freq_env: Optional[Any] = None) -> Any:
        """Return a pygame Sound from synthesised waveform."""
        n   = int(self.SR * dur)
        t   = np.linspace(0, dur, n, endpoint=False)
        f   = freq_env if freq_env is not None else np.full(n, freq)
        ph  = 2 * np.pi * np.cumsum(f) / self.SR

        if shape == "sine":
            w = np.sin(ph)
        elif shape == "square":
            w = np.sign(np.sin(ph))
        elif shape == "tri":
            w = 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
        else:
            w = np.sin(ph)

        # amplitude envelope
        env = np.ones(n)
        a   = min(int(attack  * self.SR), n // 4)
        r   = min(int(release * self.SR), n // 2)
        if a: env[:a]  = np.linspace(0, 1, a)
        if r: env[-r:] = np.linspace(1, 0, r)

        raw = (w * env * vol * 32767).astype(np.int16)
        stereo = np.column_stack([raw, raw])
        return pygame.sndarray.make_sound(stereo)

    def _noise_burst(self, dur: float = 0.12, vol: float = 0.4) -> Any:
        n   = int(self.SR * dur)
        env = np.exp(-np.linspace(0, 8, n))
        raw = (np.random.uniform(-1, 1, n) * env * vol * 32767).astype(np.int16)
        stereo = np.column_stack([raw, raw])
        return pygame.sndarray.make_sound(stereo)

    def _build(self) -> None:
        try:
            # countdown ticks  3 → 2 → 1  (same tone, just call thrice)
            self._sounds["tick"]  = self._wave(660, 0.11, "sine",  vol=0.6, release=0.08)
            # GO!  — brighter, longer
            self._sounds["go"]    = self._wave(1050, 0.22, "sine", vol=0.7, release=0.14)
            # tag impact — low thud + noise
            t_dur = 0.18
            n     = int(self.SR * t_dur)
            t_arr = np.linspace(0, t_dur, n)
            freq_sweep = 280 * np.exp(-t_arr * 14)
            ph    = 2 * np.pi * np.cumsum(freq_sweep) / self.SR
            thud  = np.sin(ph) * np.exp(-t_arr * 22)
            noise = np.random.uniform(-1, 1, n) * np.exp(-t_arr * 40) * 0.3
            raw   = ((thud + noise) * 0.65 * 32767).astype(np.int16)
            stereo = np.column_stack([raw, raw])
            self._sounds["tag"]   = pygame.sndarray.make_sound(stereo)
            # round win — 3-note ascending
            self._sounds["round_win"] = self._wave(528, 0.18, "sine", vol=0.6)
            self._sounds["round_win2"]= self._wave(660, 0.18, "sine", vol=0.6)
            self._sounds["round_win3"]= self._wave(792, 0.30, "sine", vol=0.65, release=0.22)
            # match win fanfare — 4 quick ascending notes
            self._sounds["match_win"] = self._wave(528, 0.14, "tri",  vol=0.6)
            self._sounds["match_win2"]= self._wave(660, 0.14, "tri",  vol=0.6)
            self._sounds["match_win3"]= self._wave(792, 0.14, "tri",  vol=0.6)
            self._sounds["match_win4"]= self._wave(1056, 0.45,"sine", vol=0.7, release=0.32)
            # menu click
            self._sounds["click"] = self._wave(440, 0.07, "sine", vol=0.35, release=0.05)
        except Exception:
            self.enabled = False

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        s = self._sounds.get(name)
        if s:
            s.play()

    # Pending delayed sounds: list of (play_at_time, sound_name)
    _pending: List = []

    def play_round_win(self) -> None:
        """Staggered 3-note fanfare."""
        if not self.enabled:
            return
        now = _time.time()
        for name, delay in [("round_win", 0), ("round_win2", 0.185), ("round_win3", 0.370)]:
            if self._sounds.get(name):
                self._pending.append((now + delay, name))

    def play_match_win(self) -> None:
        if not self.enabled:
            return
        now = _time.time()
        for name, delay in [("match_win", 0), ("match_win2", 0.130),
                             ("match_win3", 0.260), ("match_win4", 0.390)]:
            if self._sounds.get(name):
                self._pending.append((now + delay, name))

    def update_pending(self) -> None:
        """Call each frame to play delayed sounds when their time arrives."""
        if not self._pending:
            return
        now = _time.time()
        still_pending = []
        for play_at, name in self._pending:
            if now >= play_at:
                s = self._sounds.get(name)
                if s:
                    s.play()
            else:
                still_pending.append((play_at, name))
        self._pending = still_pending


SFX = SoundManager()


# ═════════════════════════════════════════════════════════════════════════════
#  MAP DEFINITIONS   (5 unique maps)
#  All wall rects are in SCREEN coordinates via pf()
# ═════════════════════════════════════════════════════════════════════════════

def pf(x: int, y: int, w: int, h: int) -> pygame.Rect:
    return pygame.Rect(PF_X + x, PF_Y + y, w, h)

def pfp(x: int, y: int) -> tuple:
    return (PF_X + x, PF_Y + y)

MAPS: Dict[int, Dict] = {

    # ── 1: OPEN ARENA ─────────────────────────────────────────────────────────
    1: dict(
        name  = "OPEN ARENA",
        floor = (TILE_A, TILE_B),
        p1    = pfp(168, 162),
        p2    = pfp(740, 438),
        walls = [
            pf( 55,  48, 78, 78),   pf(827,  48, 78, 78),
            pf( 55, 486, 78, 78),   pf(827, 486, 78, 78),
            pf(410, 270, 20, 72),   pf(375, 300, 90, 20),
            pf(  0, 248, 55, WT),   pf(905, 248, 55, WT),
            pf(  0, 344, 55, WT),   pf(905, 344, 55, WT),
        ],
    ),

    # ── 2: LABYRINTH ──────────────────────────────────────────────────────────
    2: dict(
        name  = "LABYRINTH",
        floor = ((12, 10, 22), (15, 12, 27)),
        p1    = pfp(48, 140),
        p2    = pfp(900, 540),
        walls = [
            pf(150,  72, 200, WT), pf(460,  72, 200, WT),
            pf(150,  72, WT, 140), pf(350,  72, WT, 140),
            pf(560,  72, WT, 140), pf(760,  72, WT, 140),
            pf(150, 212, 200, WT), pf(560, 212, 200, WT),
            pf(  0, 278,  92, WT), pf(820, 278,  92, WT),
            pf(205, 308, WT, 165), pf(710, 278, WT,  92),
            pf(510, 308, WT, 135), pf(205, 473, 305, WT),
            pf(610, 380, 180, WT), pf(205, 308, 100, WT),
            pf(410, 308, 100, WT),
            pf(100, 510, WT, 102), pf(410, 473, WT, 139),
            pf(710, 473, WT, 139), pf(100, 510, 200, WT),
            pf(510, 510, 300, WT),
        ],
    ),

    # ── 3: FOUR ROOMS ─────────────────────────────────────────────────────────
    3: dict(
        name  = "FOUR ROOMS",
        floor = ((13, 11, 24), (16, 14, 30)),
        p1    = pfp(200, 148),
        p2    = pfp(708, 440),
        walls = [
            pf(  0, 300, 400, WT),   pf(520, 300, 440, WT),
            pf(450,   0, WT, 226),   pf(450, 374, WT, 238),
            pf( 68,  62,  82, WT),   pf( 68,  62, WT,  82),
            pf(760,  62,  82, WT),   pf(842,  62, WT,  82),
            pf( 68, 472,  82, WT),   pf( 68, 444, WT,  72),
            pf(760, 472,  82, WT),   pf(842, 444, WT,  72),
        ],
    ),

    # ── 4: THE CROSS ──────────────────────────────────────────────────────────
    4: dict(
        name  = "THE CROSS",
        floor = ((11,  9, 21), (14, 12, 26)),
        p1    = pfp(390, 130),
        p2    = pfp(530, 460),
        walls = [
            pf(  0,   0, 270, 204),   pf(650,   0, 270, 204),
            pf(  0, 408, 270, 204),   pf(650, 408, 270, 204),
            pf( 98, 252,  60,  96),   pf(762, 252,  60,  96),
            pf(342,  64, 236,  54),   pf(342, 494, 236,  54),
        ],
    ),

    # ── 5: URBAN GRID ─────────────────────────────────────────────────────────
    5: dict(
        name  = "URBAN GRID",
        floor = ((12, 10, 22), (15, 13, 28)),
        p1    = pfp(168,  48),
        p2    = pfp(758, 546),
        walls = [
            pf( 78,  98, 112, WT),   pf(730,  98, 112, WT),
            pf( 78,  98, WT, 112),   pf(842,  98, WT, 112),
            pf(244, 162, WT, 124),   pf(652, 162, WT, 124),
            pf(244, 162, 164, WT),   pf(508, 162, 144, WT),
            pf(344, 286, WT, 112),   pf(572, 286, WT, 112),
            pf(154, 306, 154, WT),   pf(612, 306, 154, WT),
            pf(154, 306, WT, 152),   pf(766, 306, WT, 152),
            pf(  0, 366,  82, WT),   pf(838, 366,  82, WT),
            pf(244, 438, 132, WT),   pf(544, 438, 132, WT),
            pf(244, 438, WT, 102),   pf(676, 438, WT, 102),
            pf( 78, 474, 118, WT),   pf(724, 474, 118, WT),
            pf( 78, 474, WT,  82),   pf(842, 474, WT,  82),
        ],
    ),
}


# ═════════════════════════════════════════════════════════════════════════════
#  PARTICLES  +  SCREEN SHAKE  +  FLOATING TEXT
# ═════════════════════════════════════════════════════════════════════════════

class Particle:
    __slots__ = ('x','y','vx','vy','life','max_life','r','col','grav')
    def __init__(self, x,y,vx,vy,life,r,col,grav=210.0):
        self.x=x; self.y=y; self.vx=vx; self.vy=vy
        self.life=self.max_life=life; self.r=r; self.col=col; self.grav=grav
    def update(self, dt:float)->bool:
        self.vy+=self.grav*dt; self.x+=self.vx*dt; self.y+=self.vy*dt
        self.life-=dt; return self.life>0
    def draw(self, surf:pygame.Surface)->None:
        t=max(0.0,self.life/self.max_life)
        rad=max(1,int(self.r*t))
        col=tuple(int(c*t) for c in self.col)
        pygame.draw.circle(surf,col,(int(self.x),int(self.y)),rad)


class FloatingText:
    """Text that drifts upward and fades out (e.g. "TAG!")."""
    def __init__(self, x:float, y:float, text:str, color:tuple,
                 size:int=30, life:float=1.1):
        self.x=x; self.y=y; self.text=text; self.color=color
        self.life=self.max_life=life
        self._surf=_mkfont(size,True).render(text,True,color)
    def update(self, dt:float)->bool:
        self.y -= 50*dt; self.life-=dt; return self.life>0
    def draw(self, surf:pygame.Surface)->None:
        t=max(0.0,self.life/self.max_life)
        alpha=int(255*min(1.0,t*2.5))
        s=self._surf.copy(); s.set_alpha(alpha)
        surf.blit(s,s.get_rect(center=(int(self.x),int(self.y))))


class ScreenShake:
    def __init__(self): self.trauma=0.0
    def hit(self, amount:float=1.0): self.trauma=min(1.0,self.trauma+amount)
    def update(self, dt:float): self.trauma=max(0.0,self.trauma-dt*3.2)
    @property
    def offset(self)->tuple:
        if self.trauma<0.01: return (0,0)
        s=self.trauma**2*13
        return (random.uniform(-s,s), random.uniform(-s,s))


def _jitter(col:tuple, spread:int=30)->tuple:
    return tuple(min(255,max(0,c+random.randint(-spread,spread))) for c in col)

def emit_burst(ps:list, x:float, y:float, col:tuple, n:int=28, spd:float=195)->None:
    for _ in range(n):
        a=random.uniform(0,math.tau); v=random.uniform(spd*0.15,spd)
        li=random.uniform(0.28,0.75); r=random.uniform(2.5,6.5)
        ps.append(Particle(x,y,math.cos(a)*v,math.sin(a)*v,li,r,_jitter(col,35)))

def emit_trail(ps:list, x:float, y:float, col:tuple, vx:float, vy:float)->None:
    if abs(vx)+abs(vy)<40: return
    a=random.uniform(0,math.tau); li=random.uniform(0.07,0.22)
    ps.append(Particle(x+random.uniform(-3,3),y+random.uniform(-3,3),
                       math.cos(a)*25,math.sin(a)*25,li,
                       random.uniform(1.5,3.5),_jitter(col,45),grav=0.0))


# ═════════════════════════════════════════════════════════════════════════════
#  GLOW SURFACE CACHE
# ═════════════════════════════════════════════════════════════════════════════

_glow_cache: Dict = {}

def glow_surf(radius:int, col:tuple)->pygame.Surface:
    key=(radius,col)
    if key not in _glow_cache:
        s=pygame.Surface((radius*2,radius*2),pygame.SRCALPHA)
        for i in range(radius,0,-3):
            a=int(152*(i/radius)**2.5)
            pygame.draw.circle(s,(*col,a),(radius,radius),i)
        _glow_cache[key]=s
    return _glow_cache[key]


# ═════════════════════════════════════════════════════════════════════════════
#  PLAYER
# ═════════════════════════════════════════════════════════════════════════════

class Player:
    def __init__(self, pid:int, start:tuple, color:tuple, keys:tuple):
        self.pid   = pid
        self.pos   = Vector2(start)
        self.vel   = Vector2(0.0,0.0)
        self.color = color
        self.keys  = keys          # (up, down, left, right)
        self.is_it = False
        self.score = 0.0
        self.grace = 0.0
        self.net_keys: Optional[Dict] = None   # set when network-controlled
        self._pulse    = random.uniform(0,math.tau)
        self._trail_t  = 0.0
        self._it_time  = 0.0    # how long this player has been IT this round

    @property
    def rect(self)->pygame.Rect:
        h=PSZ//2
        return pygame.Rect(int(self.pos.x)-h,int(self.pos.y)-h,PSZ,PSZ)

    def update(self, dt:float, walls:list, ps:list)->None:
        if self.grace>0: self.grace=max(0.0,self.grace-dt)
        if self.is_it:   self._it_time+=dt
        self._pulse+=dt*(5.0 if self.is_it else 2.5)

        # ── input ────────────────────────────────────────────────────────────
        if self.net_keys is not None:
            nk=self.net_keys
            dx=int(nk.get('r',0))-int(nk.get('l',0))
            dy=int(nk.get('d',0))-int(nk.get('u',0))
        else:
            kb=pygame.key.get_pressed()
            up,dn,lt,rt=self.keys
            dx=int(kb[rt])-int(kb[lt])
            dy=int(kb[dn])-int(kb[up])

        if dx or dy:
            mag=math.hypot(dx,dy)
            self.vel.x+=(dx/mag)*ACCEL*dt
            self.vel.y+=(dy/mag)*ACCEL*dt
            spd=self.vel.length()
            if spd>SPD_MAX: self.vel.scale_to_length(SPD_MAX)
        else:
            spd=self.vel.length()
            if spd>0:
                slow=min(spd,DECEL*dt)
                self.vel-=self.vel.normalize()*slow

        # ── X move + wall resolve ─────────────────────────────────────────────
        self.pos.x+=self.vel.x*dt
        r=self.rect
        for w in walls:
            if r.colliderect(w):
                if self.vel.x>0: self.pos.x=w.left -PSZ//2
                else:            self.pos.x=w.right+PSZ//2
                self.vel.x=0.0; r=self.rect

        # ── Y move + wall resolve ─────────────────────────────────────────────
        self.pos.y+=self.vel.y*dt
        r=self.rect
        for w in walls:
            if r.colliderect(w):
                if self.vel.y>0: self.pos.y=w.top   -PSZ//2
                else:            self.pos.y=w.bottom+PSZ//2
                self.vel.y=0.0; r=self.rect

        # ── boundary clamp ────────────────────────────────────────────────────
        h=PSZ//2
        self.pos.x=max(PF_X+h+1.0,min(PF_X+PF_W-h-1.0,self.pos.x))
        self.pos.y=max(PF_Y+h+1.0,min(PF_Y+PF_H-h-1.0,self.pos.y))

        # ── trail ─────────────────────────────────────────────────────────────
        self._trail_t-=dt
        if self._trail_t<=0:
            self._trail_t=0.044
            emit_trail(ps,self.pos.x,self.pos.y,self.color,self.vel.x,self.vel.y)

    def apply_state(self, d:Dict)->None:
        """Apply authoritative state received from host (online guest mode)."""
        self.pos.x=float(d['x']); self.pos.y=float(d['y'])
        self.vel.x=float(d['vx']);self.vel.y=float(d['vy'])
        self.is_it=bool(d['it']); self.score=float(d['sc'])
        self.grace=float(d['gr'])

    def get_state(self)->Dict:
        return {'x':round(self.pos.x,1),'y':round(self.pos.y,1),
                'vx':round(self.vel.x,1),'vy':round(self.vel.y,1),
                'it':self.is_it,'sc':round(self.score,2),'gr':round(self.grace,2)}

    def draw(self, surf:pygame.Surface, time_left:float=90.0)->None:
        cx,cy=int(self.pos.x),int(self.pos.y); h=PSZ//2

        # ── glow halo ─────────────────────────────────────────────────────────
        if self.is_it:
            urgency=1.0-max(0.0,min(1.0,(time_left-15)/75))  # 0..1 as time runs out
            pulse_spd=3.0+urgency*5.0
            p=(math.sin(self._pulse*pulse_spd)+1)*0.5
            gr=int(h*2.5+p*h*1.1)
            ring_col=(min(255,int(IT_RING[0]+urgency*40)),
                      max(0,int(IT_RING[1]-urgency*20)),
                      max(0,int(IT_RING[2]-urgency*20)))
            gs=glow_surf(gr,ring_col)
            surf.blit(gs,(cx-gr,cy-gr),special_flags=pygame.BLEND_RGBA_ADD)
        elif self.grace>0:
            gr=int(h*1.9)
            gs=glow_surf(gr,SAFE_C)
            tmp=pygame.Surface((gr*2,gr*2),pygame.SRCALPHA)
            tmp.blit(gs,(0,0)); tmp.set_alpha(int(188*(self.grace/GRACE)))
            surf.blit(tmp,(cx-gr,cy-gr))

        # ── shadow ────────────────────────────────────────────────────────────
        pygame.draw.rect(surf,(0,0,0),(cx-h+3,cy-h+4,PSZ,PSZ),border_radius=4)

        # ── body ──────────────────────────────────────────────────────────────
        col=self.color
        if self.grace>0 and int(self.grace/0.10)%2==0: col=SAFE_C
        body=pygame.Rect(cx-h,cy-h,PSZ,PSZ)
        pygame.draw.rect(surf,col,body,border_radius=5)
        hi=tuple(min(255,c+92) for c in col)
        sh=tuple(max(0,  c-58) for c in col)
        pygame.draw.line(surf,hi,(body.left+3, body.top+2),(body.right-3,body.top+2),2)
        pygame.draw.line(surf,hi,(body.left+2, body.top+2),(body.left+2, body.bottom-4),2)
        pygame.draw.line(surf,sh,(body.left+2, body.bottom-2),(body.right-2,body.bottom-2),2)
        pygame.draw.line(surf,sh,(body.right-2,body.top+2),(body.right-2,body.bottom-2),2)

        # ── IT ring ───────────────────────────────────────────────────────────
        if self.is_it:
            p=(math.sin(self._pulse*3.0)+1)*0.5
            rr=int(h+7+p*5)
            pygame.draw.circle(surf,IT_RING,(cx,cy),rr,2)
            lbl=F_XS.render("◆ IT ◆",True,IT_RING)
            surf.blit(lbl,lbl.get_rect(center=(cx,cy-h-12)))

        # ── player label ──────────────────────────────────────────────────────
        nm=F_SM.render(f"P{self.pid}",True,(0,0,0))
        surf.blit(nm,nm.get_rect(center=(cx,cy)))


# ═════════════════════════════════════════════════════════════════════════════
#  NETWORK MANAGER  (WebSocket relay client)
# ═════════════════════════════════════════════════════════════════════════════

class NetworkManager:
    """Non-blocking async WebSocket client with auto-reconnect & ping."""

    MAX_RECONNECT = 3
    PING_INTERVAL = 2.0     # seconds between ping measurements

    def __init__(self):
        self.ws           = None
        self.recv_q:  asyncio.Queue = asyncio.Queue()
        self.send_q:  asyncio.Queue = asyncio.Queue()
        self.connected    = False
        self.error: Optional[str]   = None
        self._recv_task   = None
        self._send_task   = None
        self._ping_task   = None
        self._url: str    = ""
        self.ping_ms: float = -1     # latest round-trip in ms (-1 = unknown)
        self.reconnecting = False
        self._reconnect_count = 0

    async def connect(self, url:str)->bool:
        if not _ONLINE_OK:
            self.error="websockets not installed (pip install websockets)"; return False
        self._url = url
        return await self._do_connect(url)

    async def _do_connect(self, url:str)->bool:
        try:
            self.ws = await websockets.connect(url, open_timeout=8,
                                                ping_interval=20, ping_timeout=20,
                                                close_timeout=10,
                                                max_size=2**16,
                                                compression=None)
            self.connected=True; self.error=None
            self._reconnect_count = 0
            self.reconnecting = False
            self._recv_task=asyncio.create_task(self._recv_loop())
            self._send_task=asyncio.create_task(self._send_loop())
            self._ping_task=asyncio.create_task(self._ping_loop())
            return True
        except Exception as e:
            self.error=str(e); self.connected=False; return False

    async def _recv_loop(self)->None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("t") == "pong":
                    sent = msg.get("ts", 0)
                    self.ping_ms = (_time.time() * 1000) - sent
                else:
                    await self.recv_q.put(msg)
        except Exception:
            pass
        finally:
            self.connected=False
            # Try auto-reconnect before signaling disconnect
            if self._reconnect_count < self.MAX_RECONNECT and self._url:
                asyncio.create_task(self._auto_reconnect())
            else:
                await self.recv_q.put({"t":"_disconnected"})

    async def _auto_reconnect(self)->None:
        self._reconnect_count += 1
        delay = min(2 ** self._reconnect_count, 8)  # 2s, 4s, 8s
        self.reconnecting = True
        self.error = f"Reconnecting ({self._reconnect_count}/{self.MAX_RECONNECT})…"
        await asyncio.sleep(delay)
        ok = await self._do_connect(self._url)
        if not ok:
            if self._reconnect_count < self.MAX_RECONNECT:
                asyncio.create_task(self._auto_reconnect())
            else:
                self.reconnecting = False
                await self.recv_q.put({"t":"_disconnected"})

    async def _send_loop(self)->None:
        try:
            while True:
                msg=await self.send_q.get()
                if msg is None: break
                if self.connected:
                    await self.ws.send(json.dumps(msg))
        except Exception:
            pass

    async def _ping_loop(self)->None:
        """Periodically measure round-trip latency via server ping."""
        try:
            while self.connected:
                await asyncio.sleep(self.PING_INTERVAL)
                if self.connected:
                    ts = _time.time() * 1000
                    self.send({"t":"ping","ts":ts})
        except Exception:
            pass

    def send(self, msg:Dict)->None:
        if self.connected: self.send_q.put_nowait(msg)

    def recv(self)->Optional[Dict]:
        try:    return self.recv_q.get_nowait()
        except asyncio.QueueEmpty: return None

    async def close(self)->None:
        self.connected=False
        self._reconnect_count = self.MAX_RECONNECT  # prevent auto-reconnect
        self.send_q.put_nowait(None)
        if self._recv_task: self._recv_task.cancel()
        if self._send_task: self._send_task.cancel()
        if self._ping_task: self._ping_task.cancel()
        if self.ws:
            try: await self.ws.close()
            except Exception: pass


# ═════════════════════════════════════════════════════════════════════════════
#  CLIPBOARD HELPERS  (Windows – subprocess fallback)
# ═════════════════════════════════════════════════════════════════════════════

def _clipboard_get() -> str:
    """Read text from the system clipboard."""
    try:
        import subprocess
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Get-Clipboard'],
            capture_output=True, text=True, timeout=2,
            creationflags=0x08000000)
        return r.stdout.strip().replace('\r\n', '').replace('\n', '')
    except Exception:
        return ""

def _clipboard_set(text: str) -> None:
    """Write text to the system clipboard."""
    try:
        import subprocess
        subprocess.Popen(
            ['clip'], stdin=subprocess.PIPE,
            creationflags=0x08000000
        ).communicate(text.encode())
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
#  TEXT INPUT WIDGET  (cursor · selection · clipboard · uppercase)
# ═════════════════════════════════════════════════════════════════════════════

class TextInput:
    """Full-featured single-line text input for pygame.

    Features
    --------
    - Cursor: ← → Home End  (Ctrl+← / Ctrl+→ word-jump)
    - Selection: Shift+arrows, Ctrl+A, click to position cursor
    - Clipboard: Ctrl+C copy, Ctrl+V paste, Ctrl+X cut
    - Delete / Backspace (respects selection)
    - force_lower: when True all input is lowered (room codes)
    """

    def __init__(self, placeholder: str = "", max_len: int = 40,
                 allowed: Optional[set] = None, font=None,
                 force_lower: bool = False):
        self.text         = ""
        self.placeholder  = placeholder
        self.max_len      = max_len
        self.allowed      = allowed
        self.font         = font or F_MD
        self.active       = False
        self.force_lower  = force_lower
        self._cursor_t    = 0.0
        # cursor & selection (-1 = no selection)
        self.cur           = 0
        self.sel_start     = -1
        self.sel_end       = -1

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def has_sel(self) -> bool:
        return (self.sel_start >= 0 and self.sel_end >= 0
                and self.sel_start != self.sel_end)

    def _sel_range(self):
        if not self.has_sel:
            return None
        return min(self.sel_start, self.sel_end), max(self.sel_start, self.sel_end)

    def _del_sel(self) -> bool:
        r = self._sel_range()
        if r:
            lo, hi = r
            self.text = self.text[:lo] + self.text[hi:]
            self.cur = lo
            self.sel_start = self.sel_end = -1
            return True
        return False

    def _clear_sel(self):
        self.sel_start = self.sel_end = -1

    def _begin_sel(self):
        if self.sel_start < 0:
            self.sel_start = self.cur
        self.sel_end = self.cur

    def select_all(self):
        self.sel_start = 0
        self.sel_end = len(self.text)
        self.cur = len(self.text)

    def _insert(self, s: str):
        self._del_sel()
        for ch in s:
            if len(self.text) >= self.max_len:
                break
            if self.force_lower:
                ch = ch.lower()
            if ch.isprintable() and not ch.isspace():
                if self.allowed is None or ch.lower() in self.allowed:
                    self.text = self.text[:self.cur] + ch + self.text[self.cur:]
                    self.cur += 1

    def _word_left(self) -> int:
        i = self.cur - 1
        while i > 0 and not self.text[i-1].isalnum():
            i -= 1
        while i > 0 and self.text[i-1].isalnum():
            i -= 1
        return max(0, i)

    def _word_right(self) -> int:
        n = len(self.text)
        i = self.cur
        while i < n and not self.text[i].isalnum():
            i += 1
        while i < n and self.text[i].isalnum():
            i += 1
        return i

    # ── event handling ────────────────────────────────────────────────────────

    def handle_key(self, ev: pygame.event.Event) -> None:
        if not self.active:
            return

        mods = pygame.key.get_mods()
        ctrl  = bool(mods & pygame.KMOD_CTRL)
        shift = bool(mods & pygame.KMOD_SHIFT)
        k = ev.key

        # ── CTRL combos ──────────────────────────────────────────────────────
        if ctrl:
            if k == pygame.K_a:
                self.select_all(); return
            if k == pygame.K_c:
                r = self._sel_range()
                _clipboard_set(self.text[r[0]:r[1]] if r else self.text)
                return
            if k == pygame.K_x:
                r = self._sel_range()
                if r:
                    _clipboard_set(self.text[r[0]:r[1]])
                    self._del_sel()
                return
            if k == pygame.K_v:
                clip = _clipboard_get()
                if clip:
                    self._insert(clip)
                return
            if k == pygame.K_LEFT:
                npos = self._word_left()
                if shift:
                    self._begin_sel(); self.cur = npos; self.sel_end = npos
                else:
                    self._clear_sel(); self.cur = npos
                return
            if k == pygame.K_RIGHT:
                npos = self._word_right()
                if shift:
                    self._begin_sel(); self.cur = npos; self.sel_end = npos
                else:
                    self._clear_sel(); self.cur = npos
                return

        # ── BACKSPACE ─────────────────────────────────────────────────────────
        if k == pygame.K_BACKSPACE:
            if not self._del_sel():
                if self.cur > 0:
                    self.text = self.text[:self.cur-1] + self.text[self.cur:]
                    self.cur -= 1
            return

        # ── DELETE ────────────────────────────────────────────────────────────
        if k == pygame.K_DELETE:
            if not self._del_sel():
                if self.cur < len(self.text):
                    self.text = self.text[:self.cur] + self.text[self.cur+1:]
            return

        # ── LEFT ──────────────────────────────────────────────────────────────
        if k == pygame.K_LEFT:
            if shift:
                if self.sel_start < 0: self.sel_start = self.cur
                self.cur = max(0, self.cur - 1); self.sel_end = self.cur
            else:
                self._clear_sel(); self.cur = max(0, self.cur - 1)
            return

        # ── RIGHT ─────────────────────────────────────────────────────────────
        if k == pygame.K_RIGHT:
            if shift:
                if self.sel_start < 0: self.sel_start = self.cur
                self.cur = min(len(self.text), self.cur + 1); self.sel_end = self.cur
            else:
                self._clear_sel(); self.cur = min(len(self.text), self.cur + 1)
            return

        # ── HOME ──────────────────────────────────────────────────────────────
        if k == pygame.K_HOME:
            if shift:
                self._begin_sel(); self.cur = 0; self.sel_end = 0
            else:
                self._clear_sel(); self.cur = 0
            return

        # ── END ───────────────────────────────────────────────────────────────
        if k == pygame.K_END:
            if shift:
                self._begin_sel(); self.cur = len(self.text); self.sel_end = self.cur
            else:
                self._clear_sel(); self.cur = len(self.text)
            return

        # ── REGULAR CHARACTER ─────────────────────────────────────────────────
        if k not in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_TAB,
                      pygame.K_LSHIFT, pygame.K_RSHIFT,
                      pygame.K_LCTRL, pygame.K_RCTRL,
                      pygame.K_LALT, pygame.K_RALT,
                      pygame.K_CAPSLOCK):
            ch = ev.unicode
            if ch and ch.isprintable():
                self._insert(ch)

    def handle_click(self, mx: int, rect: pygame.Rect) -> None:
        """Position cursor at the clicked character."""
        if not self.text:
            self.cur = 0; self._clear_sel(); return
        rel_x = mx - (rect.x + 9)
        best, best_d = 0, abs(rel_x)
        for i in range(1, len(self.text) + 1):
            w = self.font.size(self.text[:i])[0]
            d = abs(rel_x - w)
            if d < best_d:
                best, best_d = i, d
        self.cur = best
        self._clear_sel()

    # ── update & draw ─────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        self._cursor_t = (self._cursor_t + dt) % 1.0

    def draw(self, surf: pygame.Surface, rect: pygame.Rect,
             label: str = "", error: str = "") -> None:
        pygame.draw.rect(surf, (18, 14, 36), rect, border_radius=5)
        bc = TXT_P1 if self.active else (TXT_ERR if error else HUD_LINE)
        pygame.draw.rect(surf, bc, rect, 2, border_radius=5)

        ty = rect.centery
        tx = rect.x + 9

        if self.text:
            col = TXT_HI
            full = self.font.render(self.text, True, col)
            fh = full.get_height()

            # selection highlight
            if self.active and self.has_sel:
                lo, hi = self._sel_range()
                x0 = self.font.size(self.text[:lo])[0]
                x1 = self.font.size(self.text[:hi])[0]
                sr = pygame.Rect(tx + x0, ty - fh // 2, x1 - x0, fh)
                pygame.draw.rect(surf, (50, 80, 160), sr)

            surf.blit(full, (tx, ty - fh // 2))

            # blinking cursor
            if self.active and self._cursor_t < 0.55:
                cx = tx + self.font.size(self.text[:self.cur])[0]
                pygame.draw.line(surf, TXT_HI,
                                 (cx, ty - fh // 2), (cx, ty + fh // 2), 2)
        else:
            ph = self.font.render(self.placeholder, True, TXT_DIM)
            surf.blit(ph, (tx, ty - ph.get_height() // 2))
            if self.active and self._cursor_t < 0.55:
                pygame.draw.line(surf, TXT_HI, (tx, ty - 10), (tx, ty + 10), 2)

        if label:
            ls = F_SM.render(label, True, TXT_DIM)
            surf.blit(ls, (rect.x, rect.y - ls.get_height() - 3))
        if error:
            es = F_SM.render(error, True, TXT_ERR)
            surf.blit(es, (rect.x, rect.bottom + 4))

# ═════════════════════════════════════════════════════════════════════════════
#  DRAWING HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def draw_floor(surf:pygame.Surface, ca:tuple, cb:tuple)->None:
    for ty in range(PF_H//TILE_SZ+2):
        for tx in range(PF_W//TILE_SZ+2):
            c=ca if (tx+ty)%2==0 else cb
            pygame.draw.rect(surf,c,(PF_X+tx*TILE_SZ,PF_Y+ty*TILE_SZ,TILE_SZ,TILE_SZ))

def draw_walls(surf:pygame.Surface, walls:list)->None:
    for w in walls:
        pygame.draw.rect(surf,WALL_F,w)
        pygame.draw.line(surf,WALL_HI,w.topleft,  w.topright,   2)
        pygame.draw.line(surf,WALL_HI,w.topleft,  w.bottomleft, 2)
        pygame.draw.line(surf,WALL_SH,w.bottomleft,w.bottomright,2)
        pygame.draw.line(surf,WALL_SH,w.topright,  w.bottomright,2)

def draw_hud(surf:pygame.Surface, p1:'Player', p2:'Player',
             time_left:float, p1_wins:int, p2_wins:int,
             map_id:int, map_name:str, round_num:int)->None:

    pygame.draw.rect(surf,HUD_BG,(0,0,WIN_W,HUD_H))
    pygame.draw.line(surf,HUD_LINE,(0,HUD_H-1),(WIN_W,HUD_H-1),2)

    # ── win stars ─────────────────────────────────────────────────────────────
    def win_stars(n:int)->str:
        return "★"*n+"☆"*(WIN_ROUNDS-n)

    BAR_W,BAR_H=148,7
    ROW1=10; ROW2=38

    # ── P1 left side ──────────────────────────────────────────────────────────
    it1="  ◆IT◆" if p1.is_it else ""
    p1txt=F_MD.render(f"P1  {win_stars(p1_wins)}  {int(p1.score):>3}pt{it1}",
                      True, TXT_IT if p1.is_it else TXT_P1)
    surf.blit(p1txt,(12,ROW1))

    bx1=12
    pygame.draw.rect(surf,(22,18,44),(bx1,ROW2,BAR_W,BAR_H),border_radius=3)
    # hot potato: bar shows how much score you have out of theoretical max
    max_pts=ROUND_TIME*SCORE_RATE
    fw1=int(BAR_W*min(1.0,p1.score/max(1,max_pts)))
    if fw1>0:
        pygame.draw.rect(surf,TXT_P1,(bx1,ROW2,fw1,BAR_H),border_radius=3)

    # ── timer centre ──────────────────────────────────────────────────────────
    tl=max(0.0,time_left)
    mm,ss=int(tl//60),int(tl%60)
    t_col=TXT_IT if tl<10 else TXT_HI
    if tl<10 and int(tl*3)%2==0: t_col=(255,255,255)
    t_surf=F_LG.render(f"{mm:02d}:{ss:02d}",True,t_col)
    surf.blit(t_surf,t_surf.get_rect(center=(WIN_W//2,ROW1+t_surf.get_height()//2)))

    r_surf=F_SM.render(f"R{round_num}",True,TXT_DIM)
    surf.blit(r_surf,r_surf.get_rect(center=(WIN_W//2,ROW2+r_surf.get_height()//2+1)))

    # ── map name ──────────────────────────────────────────────────────────────
    info=F_XS.render(f"MAP {map_id}: {map_name}  [1-5]",True,TXT_DIM)
    surf.blit(info,info.get_rect(center=(WIN_W//2,HUD_H-9)))

    # ── P2 right side ─────────────────────────────────────────────────────────
    it2="◆IT◆  " if p2.is_it else ""
    p2txt=F_MD.render(f"{it2}{int(p2.score):>3}pt  {win_stars(p2_wins)}  P2",
                      True, TXT_IT if p2.is_it else TXT_P2)
    surf.blit(p2txt,(WIN_W-p2txt.get_width()-12,ROW1))

    bx2=WIN_W-12-BAR_W
    pygame.draw.rect(surf,(22,18,44),(bx2,ROW2,BAR_W,BAR_H),border_radius=3)
    fw2=int(BAR_W*min(1.0,p2.score/max(1,max_pts)))
    if fw2>0:
        pygame.draw.rect(surf,TXT_P2,(WIN_W-12-fw2,ROW2,fw2,BAR_H),border_radius=3)

    # ── hot potato hint ───────────────────────────────────────────────────────
    hint=F_XS.render("🥔 IT = score burns!",True,(120,90,60))
    surf.blit(hint,(WIN_W//2-hint.get_width()//2,ROW2-1))


def draw_ping_badge(surf:pygame.Surface, ping_ms:float, reconnecting:bool)->None:
    """Small connection quality badge in top-right corner during online play."""
    if reconnecting:
        txt="⚡ RECONNECTING"; col=TXT_ERR
    elif ping_ms<0:
        txt="● --ms"; col=TXT_DIM
    elif ping_ms<60:
        txt=f"● {int(ping_ms)}ms"; col=TXT_OK
    elif ping_ms<150:
        txt=f"● {int(ping_ms)}ms"; col=TXT_WIN
    else:
        txt=f"● {int(ping_ms)}ms"; col=TXT_ERR
    s=F_XS.render(txt,True,col)
    surf.blit(s,(WIN_W-s.get_width()-8,HUD_H+4))


def draw_countdown_overlay(surf:pygame.Surface, label:str,
                            t_frac:float, pulse:float)->None:
    """Full-field countdown overlay (3 / 2 / 1 / GO!)."""
    ov=pygame.Surface((WIN_W,WIN_H),pygame.SRCALPHA)
    ov.fill((0,0,0,100)); surf.blit(ov,(0,0))

    scale=0.6+t_frac*0.5            # grows from 0.6 → 1.1 at start of step
    col_val=int(200+55*math.sin(pulse*4))
    is_go=(label=="GO!")
    base_col=TXT_WIN if is_go else TXT_HI

    for font, extra in [(F_HUGE,0)]:
        s=font.render(label,True,base_col)
        w,h_=int(s.get_width()*scale),int(s.get_height()*scale)
        if w>0 and h_>0:
            scaled=pygame.transform.scale(s,(w,h_))
            scaled.set_alpha(int(240*min(1.0,t_frac*2.5)))
            surf.blit(scaled,scaled.get_rect(center=(WIN_W//2,WIN_H//2)))


def draw_round_end_overlay(surf:pygame.Surface, p1:'Player', p2:'Player',
                            rw:'Player|None', p1_wins:int, p2_wins:int,
                            timer:float, pulse:float)->None:
    ov=pygame.Surface((WIN_W,WIN_H),pygame.SRCALPHA)
    ov.fill((0,0,0,178)); surf.blit(ov,(0,0))

    if rw:
        col=TXT_P1 if rw.pid==1 else TXT_P2
        w1=F_XL.render(f"PLAYER {rw.pid}  WINS  THE ROUND!",True,col)
    else:
        w1=F_XL.render("ROUND  DRAW!",True,TXT_WIN)
    surf.blit(w1,w1.get_rect(center=(WIN_W//2,WIN_H//2-120)))

    for i,(p,c) in enumerate([(p1,TXT_P1),(p2,TXT_P2)]):
        it_tag="  ◆ IT ◆" if p.is_it else ""
        s=F_MD.render(f"P{p.pid}: {int(p.score)} pts{it_tag}",True,c)
        surf.blit(s,s.get_rect(center=(WIN_W//2,WIN_H//2-48+i*34)))

    def stars(n): return "★"*n+"☆"*(WIN_ROUNDS-n)
    sc=F_LG.render(f"{stars(p1_wins)}  P1  vs  P2  {stars(p2_wins)}",True,TXT_HI)
    surf.blit(sc,sc.get_rect(center=(WIN_W//2,WIN_H//2+36)))

    secs=max(0,int(timer)+1)
    ns=F_MD.render(f"Next round in {secs}…",True,TXT_DIM)
    surf.blit(ns,ns.get_rect(center=(WIN_W//2,WIN_H//2+90)))


def draw_match_end_overlay(surf:pygame.Surface, p1:'Player', p2:'Player',
                            winner:'Player|None', p1_wins:int, p2_wins:int,
                            pulse:float)->None:
    ov=pygame.Surface((WIN_W,WIN_H),pygame.SRCALPHA)
    ov.fill((0,0,0,200)); surf.blit(ov,(0,0))

    # star burst
    p=(math.sin(pulse*2.8)+1)*0.5
    if winner:
        col=TXT_P1 if winner.pid==1 else TXT_P2
        w1=F_HUGE.render(f"P{winner.pid}  WINS  THE  MATCH!",True,col)
    else:
        w1=F_HUGE.render("MATCH  TIED!",True,TXT_WIN)
        col=TXT_WIN
    # glow pass
    gs=glow_surf(min(w1.get_width()//2,180),col)
    surf.blit(gs,(WIN_W//2-gs.get_width()//2,WIN_H//2-170),
              special_flags=pygame.BLEND_RGBA_ADD)
    surf.blit(w1,w1.get_rect(center=(WIN_W//2,WIN_H//2-130)))

    def stars(n): return "★"*n+"☆"*(WIN_ROUNDS-n)
    sc=F_LG.render(f"P1  {stars(p1_wins)}  vs  {stars(p2_wins)}  P2",True,TXT_HI)
    surf.blit(sc,sc.get_rect(center=(WIN_W//2,WIN_H//2-45)))

    for i,(p,c) in enumerate([(p1,TXT_P1),(p2,TXT_P2)]):
        s=F_MD.render(f"P{p.pid}: {int(p.score)} pts this round",True,c)
        surf.blit(s,s.get_rect(center=(WIN_W//2,WIN_H//2+18+i*34)))

    a=int(128+127*math.sin(pulse*3.5))
    pr=F_LG.render("ENTER  →  Play Again    ESC  →  Menu",True,(a,a,a))
    surf.blit(pr,pr.get_rect(center=(WIN_W//2,WIN_H-50)))


def draw_menu(surf:pygame.Surface, pulse:float, map_id:int,
              online_available:bool)->None:
    surf.fill(BG)
    m=MAPS[map_id]
    draw_floor(surf,*m['floor'])

    # animated background particles
    p=(math.sin(pulse*2.1)+1)*0.5
    col=(int(60+p*50),40,int(140+p*80))
    gs=glow_surf(260,col)
    surf.blit(gs,(WIN_W//2-260,WIN_H//2-200),special_flags=pygame.BLEND_RGBA_ADD)

    # title
    t_col=(int(155+100*math.sin(pulse*1.8)),
           int(80 +40 *math.sin(pulse*2.2+0.5)),
           int(220+35 *math.sin(pulse*2.6+1.0)))
    shadow=F_XL.render("NEON  TAG",True,t_col)
    title =F_XL.render("NEON  TAG",True,TXT_HI)
    surf.blit(shadow,shadow.get_rect(center=(WIN_W//2+3,148+2)))
    surf.blit(title, title.get_rect(center=(WIN_W//2,  148)))

    rows=[
        ("HOT POTATO RULES",                                     TXT_WIN),
        ("",                                                      TXT_DIM),
        ("P1 (Cyan)    →  W A S D",                              TXT_P1),
        ("P2 (Orange)  →  Arrow Keys",                           TXT_P2),
        ("",                                                      TXT_DIM),
        ("1 – 5  Switch Map    R  Restart    ESC  Menu",         TXT_HI),
        ("",                                                      TXT_DIM),
        ("NOT IT: +1 pt/s     IS IT: −0.8 pt/s   (90s rounds)", TXT_DIM),
        ("Best of 3 rounds  →  first to 2 round-wins",          TXT_DIM),
    ]
    for i,(txt,c) in enumerate(rows):
        s=F_MD.render(txt,True,c)
        surf.blit(s,s.get_rect(center=(WIN_W//2,238+i*30)))

    # online hint
    if online_available:
        ot=F_MD.render("O  →  Online Play",True,TXT_OK)
    else:
        ot=F_MD.render("pip install websockets  to enable online",True,TXT_DIM)
    surf.blit(ot,ot.get_rect(center=(WIN_W//2,WIN_H-70)))

    a=int(128+127*math.sin(pulse*3.8))
    pr=F_LG.render("PRESS  ENTER  /  SPACE  TO  PLAY",True,(a,a,a))
    surf.blit(pr,pr.get_rect(center=(WIN_W//2,WIN_H-36)))

    mn=F_SM.render(f"Map {map_id}: {MAPS[map_id]['name']}",True,TXT_DIM)
    surf.blit(mn,mn.get_rect(center=(WIN_W//2,WIN_H-12)))


def draw_online_menu(surf:pygame.Surface,
                     url_input:'TextInput', code_input:'TextInput',
                     sub_state:str, status:str, status_col:tuple,
                     code_display:str, pulse:float)->None:
    surf.fill(BG)
    draw_floor(surf,TILE_A,TILE_B)
    ov=pygame.Surface((WIN_W,WIN_H),pygame.SRCALPHA); ov.fill((0,0,6,120))
    surf.blit(ov,(0,0))

    title=F_LG.render("ONLINE  PLAY",True,TXT_P1)
    surf.blit(title,title.get_rect(center=(WIN_W//2,56)))

    # server URL
    url_rect=pygame.Rect(WIN_W//2-240,102,480,36)
    url_input.draw(surf,url_rect,label="Server URL (run neon_tag_server.py)")

    if sub_state=="choose":
        # HOST / JOIN buttons
        bw,bh=180,52
        hx,jx=WIN_W//2-bw-20,WIN_W//2+20
        by=184
        p=(math.sin(pulse*2.5)+1)*0.5

        hcol=(int(40+p*20),int(100+p*60),int(200+p*55))
        jcol=(int(180+p*50),int(80+p*30),int(30+p*15))

        pygame.draw.rect(surf,hcol,(hx,by,bw,bh),border_radius=8)
        pygame.draw.rect(surf,jcol,(jx,by,bw,bh),border_radius=8)
        pygame.draw.rect(surf,TXT_P1,(hx,by,bw,bh),2,border_radius=8)
        pygame.draw.rect(surf,TXT_P2,(jx,by,bw,bh),2,border_radius=8)

        h_lbl=F_LG.render("HOST",True,TXT_HI)
        j_lbl=F_LG.render("JOIN",True,TXT_HI)
        surf.blit(h_lbl,h_lbl.get_rect(center=(hx+bw//2,by+bh//2)))
        surf.blit(j_lbl,j_lbl.get_rect(center=(jx+bw//2,by+bh//2)))

        for i,(txt,c) in enumerate([
            ("H → Host a room and share code with friend",    TXT_P1),
            ("J → Join a friend's room with their code",      TXT_P2),
            ("You are always P1 (Cyan) as Host",              TXT_DIM),
            ("You are always P2 (Orange) as Guest",           TXT_DIM),
            ("",                                               TXT_DIM),
            ("★ Players do NOT need same WiFi / network! ★", TXT_OK),
        ]):
            s=F_SM.render(txt,True,c)
            surf.blit(s,s.get_rect(center=(WIN_W//2,270+i*22)))

    elif sub_state=="waiting":
        # waiting for partner – show big code
        cd=code_display.upper()
        lbl=F_MD.render("Share this code with your friend:",True,TXT_DIM)
        surf.blit(lbl,lbl.get_rect(center=(WIN_W//2,188)))
        p=(math.sin(pulse*3.0)+1)*0.5
        cc=tuple(min(255,int(c+p*40)) for c in TXT_P1)
        cs=F_HUGE.render(cd,True,cc)
        gs_c=glow_surf(cs.get_width()//2+20,TXT_P1)
        surf.blit(gs_c,(WIN_W//2-gs_c.get_width()//2,WIN_H//2-100),
                  special_flags=pygame.BLEND_RGBA_ADD)
        surf.blit(cs,cs.get_rect(center=(WIN_W//2,WIN_H//2-60)))

        cp=F_SM.render("(code copied to clipboard!)",True,TXT_OK)
        surf.blit(cp,cp.get_rect(center=(WIN_W//2,WIN_H//2-10)))

        a=int(100+100*math.sin(pulse*4.0))
        wt=F_MD.render("Waiting for player 2  …",True,(a,a,a))
        surf.blit(wt,wt.get_rect(center=(WIN_W//2,WIN_H//2+50)))

        nt=F_SM.render("Your friend can be on a different network!",True,TXT_DIM)
        surf.blit(nt,nt.get_rect(center=(WIN_W//2,WIN_H//2+80)))

    elif sub_state=="joining":
        # enter code
        cr=pygame.Rect(WIN_W//2-100,190,200,44)
        code_input.draw(surf,cr,label="Enter 4-letter room code:")
        j_lbl=F_MD.render("Press ENTER to connect",True,TXT_DIM)
        surf.blit(j_lbl,j_lbl.get_rect(center=(WIN_W//2,256)))

    # status line
    if status:
        ss=F_MD.render(status,True,status_col)
        surf.blit(ss,ss.get_rect(center=(WIN_W//2,WIN_H-80)))

    tip=F_SM.render("ESC → Back",True,TXT_DIM)
    surf.blit(tip,tip.get_rect(center=(WIN_W//2,WIN_H-20)))

    dep=F_XS.render("Free hosting: Render.com  (see render.yaml)",True,TXT_DIM)
    surf.blit(dep,dep.get_rect(center=(WIN_W//2,WIN_H-40)))


# ═════════════════════════════════════════════════════════════════════════════
#  GAME  (main state machine)
# ═════════════════════════════════════════════════════════════════════════════

# Countdown step: (label, duration_seconds)
_CD_STEPS = [("3",0.85),("2",0.85),("1",0.85),("GO!",0.62)]

class Game:
    MENU          = "menu"
    ONLINE_MENU   = "online_menu"
    COUNTDOWN     = "countdown"
    PLAYING       = "playing"
    ROUND_END     = "round_end"
    MATCH_END     = "match_end"

    def __init__(self):
        self.state     = self.MENU
        self.map_id    = 1
        self.pulse     = 0.0
        self.p1:  Optional[Player] = None
        self.p2:  Optional[Player] = None
        self.walls:    list = []
        self.floor_ca  = TILE_A
        self.floor_cb  = TILE_B
        # round / match state
        self.time_left = ROUND_TIME
        self.p1_wins   = 0
        self.p2_wins   = 0
        self.round_num = 1
        self.round_winner: Optional[Player] = None
        # countdown
        self.cd_idx    = 0
        self.cd_timer  = _CD_STEPS[0][1]
        # effects
        self.ps:    List[Particle]     = []
        self.floats:List[FloatingText] = []
        self.shake  = ScreenShake()
        self.flash  = 0.0
        # round-end pause timer
        self.re_timer = 0.0
        # online
        self.net: Optional[NetworkManager] = None
        self.online_role: Optional[str]    = None  # 'host' | 'guest'
        self.online_sub   = "choose"   # choose | waiting | joining
        self.online_code  = ""
        self.net_status   = ""
        self.net_status_c = TXT_DIM
        self._connecting  = False
        self.url_input    = TextInput("wss://your-app.onrender.com", 80)
        self.url_input.text = "ws://localhost:8765"
        self.url_input.cur  = len(self.url_input.text)
        self.code_input   = TextInput("abcd", 4,
                                       allowed=set("abcdefghijklmnopqrstuvwxyz"),
                                       force_lower=True)
        # guest buffered remote input from prev net message
        self._guest_input: Dict = {'u':0,'d':0,'l':0,'r':0}
        # network throttle: only send input when changed, throttle host state
        self._last_sent_input: Dict = {'u':0,'d':0,'l':0,'r':0}
        self._host_send_acc: float = 0.0       # accumulator for host send rate
        self._host_send_interval: float = 1.0/20.0  # 20 Hz state updates
        # tag event flag for syncing effects to guest
        self._tag_happened: bool = False
        self._load_map(1)

    # ── map loading ───────────────────────────────────────────────────────────

    def _load_map(self, n:int, keep_wins:bool=False)->None:
        self.map_id = n
        m = MAPS[n]
        self.walls   = m['walls']
        fc           = m['floor']
        self.floor_ca, self.floor_cb = fc

        p1_keys=(pygame.K_w,pygame.K_s,pygame.K_a,pygame.K_d)
        p2_keys=(pygame.K_UP,pygame.K_DOWN,pygame.K_LEFT,pygame.K_RIGHT)

        self.p1=Player(1,m['p1'],P1C,p1_keys)
        self.p2=Player(2,m['p2'],P2C,p2_keys)

        # In online mode, P2 is net-controlled on host
        if self.online_role=="host" and self.net:
            self.p2.net_keys=self._guest_input

        # Randomly assign IT, give prey start immunity
        if random.random()<0.5:
            self.p1.is_it=True;  self.p2.grace=START_GR
        else:
            self.p2.is_it=True;  self.p1.grace=START_GR

        self.time_left=ROUND_TIME
        self.ps=[]; self.floats=[]; self.flash=0.0
        self.round_winner=None

        if not keep_wins:
            self.p1_wins=0; self.p2_wins=0; self.round_num=1

    def _start_countdown(self)->None:
        self.state    = self.COUNTDOWN
        self.cd_idx   = 0
        self.cd_timer = _CD_STEPS[0][1]
        SFX.play("tick")

    def _start_round(self)->None:
        self.state=self.PLAYING
        self.time_left=ROUND_TIME

    # ── tag check ─────────────────────────────────────────────────────────────

    def _check_tag(self)->None:
        if not (self.p1 and self.p2): return
        it   = self.p1 if self.p1.is_it else self.p2
        prey = self.p2 if self.p1.is_it else self.p1
        if prey.grace>0: return
        if it.rect.colliderect(prey.rect):
            # TAG!
            self._trigger_tag_effects(prey.pos.x, prey.pos.y)
            it.is_it=False; it.grace=GRACE
            prey.is_it=True; prey.grace=0.0
            prey._it_time=0.0
            self._tag_happened = True   # signal to send to guest

    def _trigger_tag_effects(self, x: float, y: float) -> None:
        """Play tag sound + visual effects. Used by both host and guest."""
        SFX.play("tag")
        emit_burst(self.ps, x, y, FLASH_C, n=30, spd=200)
        self.floats.append(FloatingText(x, y - 20, "TAG!", TAG_C, 30, 1.0))
        self.shake.hit(0.9)
        self.flash = 0.28

    # ── round end ─────────────────────────────────────────────────────────────

    def _end_round(self)->None:
        """Called when timer hits 0."""
        s1,s2=self.p1.score,self.p2.score
        if s1>s2:   rw=self.p1
        elif s2>s1: rw=self.p2
        else:       rw=None

        self.round_winner=rw
        if rw:
            if rw.pid==1: self.p1_wins+=1
            else:         self.p2_wins+=1
            SFX.play_round_win()
            emit_burst(self.ps,rw.pos.x,rw.pos.y,rw.color,n=40,spd=220)
        else:
            emit_burst(self.ps,WIN_W//2,WIN_H//2,TXT_WIN,n=30,spd=180)

        # check match winner
        if self.p1_wins>=WIN_ROUNDS or self.p2_wins>=WIN_ROUNDS:
            self.state=self.MATCH_END
            SFX.play_match_win()
            emit_burst(self.ps,WIN_W//2,WIN_H//2,TXT_WIN,n=60,spd=260)
        else:
            self.state=self.ROUND_END
            self.re_timer=3.2

    # ── network message handler ───────────────────────────────────────────────

    def _handle_net_msg(self, msg:Dict)->None:
        t=msg.get("t","")

        if t=="partner_joined" and self.online_role=="host":
            self.net_status="Partner joined!  Starting…"; self.net_status_c=TXT_OK
            # Start with current map
            self.net.send({"t":"map","map":self.map_id})
            self._load_map(self.map_id,keep_wins=True)
            self._start_countdown()
            self.state=self.COUNTDOWN   # override online_menu → countdown

        elif t=="map" and self.online_role=="guest":
            mid=int(msg.get("map",1))
            self._load_map(mid,keep_wins=True)

        elif t=="state" and self.online_role=="guest":
            # Apply authoritative state from host
            if self.p1 and "p1" in msg: self.p1.apply_state(msg["p1"])
            if self.p2 and "p2" in msg: self.p2.apply_state(msg["p2"])
            self.time_left=float(msg.get("tl",ROUND_TIME))
            self.p1_wins  =int(msg.get("w1",0))
            self.p2_wins  =int(msg.get("w2",0))
            self.round_num=int(msg.get("rn",1))
            # Tag effects sync: host signals when a tag happened
            if msg.get("tag") and self.p2:
                tx = float(msg["tag"].get("x", self.p2.pos.x))
                ty = float(msg["tag"].get("y", self.p2.pos.y))
                self._trigger_tag_effects(tx, ty)
            ph=msg.get("ph","playing")
            if ph=="countdown":
                if self.state not in (self.COUNTDOWN,):
                    self.state=self.COUNTDOWN
                self.cd_idx  =int(msg.get("cd",0))
                self.cd_timer=float(msg.get("cdt",0.5))
            elif ph=="playing" and self.state!=self.PLAYING:
                self.state=self.PLAYING
            elif ph=="round_end" and self.state!=self.ROUND_END:
                self.round_winner=(self.p1 if msg.get("rw")==1
                                   else (self.p2 if msg.get("rw")==2 else None))
                self.re_timer=float(msg.get("ret",3.2))
                self.state=self.ROUND_END
            elif ph=="match_end" and self.state!=self.MATCH_END:
                self.state=self.MATCH_END

        elif t=="input" and self.online_role=="host":
            # Store guest's input for P2 (applied each frame)
            self._guest_input={'u':int(msg.get('u',0)),'d':int(msg.get('d',0)),
                                'l':int(msg.get('l',0)),'r':int(msg.get('r',0))}
            if self.p2: self.p2.net_keys=self._guest_input

        elif t=="_disconnected" or t=="partner_left":
            self.net_status="Connection lost"; self.net_status_c=TXT_ERR
            self.online_role=None
            if self.state not in (self.MENU,self.ONLINE_MENU):
                self.state=self.ONLINE_MENU
                self.online_sub="choose"

    # ── update ────────────────────────────────────────────────────────────────

    def update(self, dt:float)->None:
        self.pulse+=dt
        SFX.update_pending()  # play delayed fanfare notes

        # process network messages every frame
        if self.net:
            while True:
                msg=self.net.recv()
                if msg is None: break
                self._handle_net_msg(msg)

        if self.state==self.MENU:
            return

        if self.state==self.ONLINE_MENU:
            self.url_input.update(dt)
            self.code_input.update(dt)
            return

        if self.state==self.COUNTDOWN:
            label,dur=_CD_STEPS[self.cd_idx]
            self.cd_timer-=dt
            if self.cd_timer<=0:
                self.cd_idx+=1
                if self.cd_idx>=len(_CD_STEPS):
                    self._start_round()
                    # in online host mode: don't re-send, state msgs carry phase
                else:
                    lbl2,dur2=_CD_STEPS[self.cd_idx]
                    self.cd_timer=dur2
                    if lbl2=="GO!": SFX.play("go")
                    else:           SFX.play("tick")
            # animate particles during countdown
            self.ps=[p for p in self.ps if p.update(dt)]
            self.floats=[f for f in self.floats if f.update(dt)]
            # online host sends state during countdown too
            if self.online_role=="host" and self.net:
                self._send_host_state(phase="countdown")
            return

        if self.state==self.ROUND_END:
            self.re_timer-=dt
            self.ps=[p for p in self.ps if p.update(dt)]
            self.floats=[f for f in self.floats if f.update(dt)]
            self.shake.update(dt)
            if self.online_role=="host" and self.net:
                self._send_host_state(phase="round_end")
            if self.re_timer<=0 and self.online_role!="guest":
                self.round_num+=1
                self._load_map(self.map_id,keep_wins=True)
                if self.online_role=="host":
                    self.net.send({"t":"map","map":self.map_id})
                    self.p2.net_keys=self._guest_input
                self._start_countdown()
            return

        if self.state==self.MATCH_END:
            self.ps=[p for p in self.ps if p.update(dt)]
            self.floats=[f for f in self.floats if f.update(dt)]
            if self.online_role=="host" and self.net:
                self._send_host_state(phase="match_end")
            return

        # ── PLAYING ───────────────────────────────────────────────────────────
        self.shake.update(dt)
        self.flash=max(0.0,self.flash-dt)

        # Only host (or local) runs the simulation
        if self.online_role!="guest":
            self.time_left=max(0.0,self.time_left-dt)

            # Hot-potato scoring
            for p in (self.p1,self.p2):
                if p.is_it: p.score=max(0.0,p.score-BURN_RATE*dt)
                else:        p.score+=SCORE_RATE*dt

            self.p1.update(dt,self.walls,self.ps)
            self.p2.update(dt,self.walls,self.ps)
            self._check_tag()

            self.ps=[p for p in self.ps if p.update(dt)]
            self.floats=[f for f in self.floats if f.update(dt)]

            if self.time_left<=0:
                self._end_round()
        else:
            # GUEST: only update visuals (particles etc.), send our input
            self.ps=[p for p in self.ps if p.update(dt)]
            self.floats=[f for f in self.floats if f.update(dt)]
            if self.net:
                kb=pygame.key.get_pressed()
                # Guest can use WASD *or* Arrow keys (whichever is pressed)
                cur_input={'u':int(kb[pygame.K_UP]   or kb[pygame.K_w]),
                           'd':int(kb[pygame.K_DOWN] or kb[pygame.K_s]),
                           'l':int(kb[pygame.K_LEFT] or kb[pygame.K_a]),
                           'r':int(kb[pygame.K_RIGHT]or kb[pygame.K_d])}
                # Only send when input actually changes
                if cur_input != self._last_sent_input:
                    self._last_sent_input = cur_input.copy()
                    self.net.send({"t":"input", **cur_input})

        # online host: send authoritative state at throttled rate (20 Hz)
        if self.online_role=="host" and self.net:
            self._host_send_acc += dt
            if self._host_send_acc >= self._host_send_interval:
                self._host_send_acc = 0.0
                self._send_host_state(phase="playing")

    def _send_host_state(self, phase:str)->None:
        """Build & queue state message to guest."""
        if not (self.net and self.p1 and self.p2): return
        extra={}
        if phase=="countdown":
            extra={"cd":self.cd_idx,"cdt":round(self.cd_timer,3)}
        elif phase=="round_end":
            rw=self.round_winner.pid if self.round_winner else 0
            extra={"rw":rw,"ret":round(self.re_timer,2)}
        # Include tag event info so guest can play effects locally
        if self._tag_happened:
            prey = self.p2 if self.p1.is_it else self.p1
            extra["tag"] = {"x": round(prey.pos.x, 1), "y": round(prey.pos.y, 1)}
            self._tag_happened = False
        self.net.send({"t":"state","ph":phase,
                       "tl":round(self.time_left,2),
                       "w1":self.p1_wins,"w2":self.p2_wins,
                       "rn":self.round_num,
                       "p1":self.p1.get_state(),
                       "p2":self.p2.get_state(),
                       **extra})

    # ── draw ─────────────────────────────────────────────────────────────────

    def draw(self)->None:
        if self.state==self.MENU:
            draw_menu(screen,self.pulse,self.map_id,_ONLINE_OK)
            pygame.display.flip(); return

        if self.state==self.ONLINE_MENU:
            draw_online_menu(screen,self.url_input,self.code_input,
                             self.online_sub,self.net_status,self.net_status_c,
                             self.online_code,self.pulse)
            pygame.display.flip(); return

        # ── base scene (shared by COUNTDOWN/PLAYING/ROUND_END/MATCH_END) ─────
        ox,oy=self.shake.offset
        surf=pygame.Surface((WIN_W,WIN_H)); surf.fill(BG)
        draw_floor(surf,self.floor_ca,self.floor_cb)
        draw_walls(surf,self.walls)

        for p in self.ps:   p.draw(surf)
        self.p2.draw(surf,self.time_left)
        self.p1.draw(surf,self.time_left)
        for f in self.floats: f.draw(surf)

        if self.flash>0:
            alpha=int(115*(self.flash/0.28))
            fls=pygame.Surface((WIN_W,WIN_H),pygame.SRCALPHA)
            fls.fill((*FLASH_C,alpha)); surf.blit(fls,(0,0))

        # ── ping badge (online only) ─────────────────────────────────────────
        if self.net and self.online_role:
            draw_ping_badge(surf, self.net.ping_ms, self.net.reconnecting)

        draw_hud(surf,self.p1,self.p2,self.time_left,
                 self.p1_wins,self.p2_wins,
                 self.map_id,MAPS[self.map_id]['name'],self.round_num)

        # ── overlays ──────────────────────────────────────────────────────────
        if self.state==self.COUNTDOWN:
            label,dur=_CD_STEPS[self.cd_idx]
            t_frac=1.0-self.cd_timer/dur
            draw_countdown_overlay(surf,label,t_frac,self.pulse)

        elif self.state==self.ROUND_END:
            draw_round_end_overlay(surf,self.p1,self.p2,self.round_winner,
                                   self.p1_wins,self.p2_wins,
                                   self.re_timer,self.pulse)

        elif self.state==self.MATCH_END:
            mw=(self.p1 if self.p1_wins>=WIN_ROUNDS
                else (self.p2 if self.p2_wins>=WIN_ROUNDS else None))
            draw_match_end_overlay(surf,self.p1,self.p2,mw,
                                   self.p1_wins,self.p2_wins,self.pulse)

        # apply screen shake offset
        screen.fill(BG)
        screen.blit(surf,(int(ox),int(oy)))
        pygame.display.flip()

    # ── event handling ────────────────────────────────────────────────────────

    def handle_event(self, ev:pygame.event.Event)->bool:
        """Return False to quit."""
        if ev.type==pygame.QUIT: return False

        if ev.type==pygame.KEYDOWN:
            k=ev.key

            # ── ONLINE MENU ───────────────────────────────────────────────────
            if self.state==self.ONLINE_MENU:
                self.url_input.handle_key(ev)
                if self.online_sub=="joining":
                    self.code_input.handle_key(ev)
                    if k==pygame.K_RETURN and len(self.code_input.text)==4:
                        asyncio.get_event_loop().create_task(
                            self._online_join(self.code_input.text))
                if k==pygame.K_ESCAPE:
                    if self.online_sub!="choose": self.online_sub="choose"
                    else: self.state=self.MENU
                elif k==pygame.K_h and self.online_sub=="choose":
                    asyncio.get_event_loop().create_task(self._online_host())
                elif k==pygame.K_j and self.online_sub=="choose":
                    self.online_sub="joining"; self.code_input.text=""
                    self.code_input.active=True
                return True

            # ── MOUSE for online menu buttons ─────────────────────────────────
            # (handled below in MOUSEBUTTONDOWN)

            # ── MENU ──────────────────────────────────────────────────────────
            if self.state==self.MENU:
                if k in (pygame.K_RETURN,pygame.K_SPACE):
                    self._load_map(self.map_id); self._start_countdown()
                elif k==pygame.K_o:
                    self.state=self.ONLINE_MENU
                    self.online_sub="choose"
                    self.url_input.active=False
                    self.net_status=""
                elif k==pygame.K_ESCAPE:
                    return False
                elif pygame.K_1<=k<=pygame.K_5:
                    self._load_map(k-pygame.K_0)
                return True

            # ── MATCH END ─────────────────────────────────────────────────────
            if self.state==self.MATCH_END:
                if k in (pygame.K_RETURN,pygame.K_r):
                    self.p1_wins=0; self.p2_wins=0; self.round_num=1
                    self._load_map(self.map_id); self._start_countdown()
                elif k==pygame.K_ESCAPE:
                    if self.net:
                        asyncio.get_event_loop().create_task(self.net.close())
                        self.net=None; self.online_role=None
                    self.state=self.MENU
                return True

            # ── IN ROUND ──────────────────────────────────────────────────────
            if k==pygame.K_ESCAPE:
                if self.net:
                    asyncio.get_event_loop().create_task(self.net.close())
                    self.net=None; self.online_role=None
                self.state=self.MENU
            elif k==pygame.K_r and self.online_role is None:
                self.p1_wins=0; self.p2_wins=0; self.round_num=1
                self._load_map(self.map_id); self._start_countdown()
            elif pygame.K_1<=k<=pygame.K_5 and self.online_role is None:
                n=k-pygame.K_0
                self._load_map(n,keep_wins=(self.state!=self.MENU))
                self._start_countdown()

        # ── MOUSE (online menu buttons) ───────────────────────────────────────
        if ev.type==pygame.MOUSEBUTTONDOWN and ev.button==1:
            if self.state==self.ONLINE_MENU and self.online_sub=="choose":
                bw,bh=180,52; by=184
                hx=WIN_W//2-bw-20; jx=WIN_W//2+20
                hr=pygame.Rect(hx,by,bw,bh); jr=pygame.Rect(jx,by,bw,bh)
                if hr.collidepoint(ev.pos):
                    SFX.play("click")
                    asyncio.get_event_loop().create_task(self._online_host())
                elif jr.collidepoint(ev.pos):
                    SFX.play("click")
                    self.online_sub="joining"
                    self.code_input.text=""; self.code_input.active=True
                    self.code_input.cur=0
            # activate / click-position text inputs
            if self.state==self.ONLINE_MENU:
                url_rect=pygame.Rect(WIN_W//2-240,102,480,36)
                if url_rect.collidepoint(ev.pos):
                    self.url_input.active=True
                    self.url_input.handle_click(ev.pos[0],url_rect)
                else:
                    self.url_input.active=False
                # code input (only when joining)
                if self.online_sub=="joining":
                    code_rect=pygame.Rect(WIN_W//2-100,190,200,44)
                    if code_rect.collidepoint(ev.pos):
                        self.code_input.active=True
                        self.code_input.handle_click(ev.pos[0],code_rect)
                    else:
                        self.code_input.active=False

        return True

    # ── online coroutines ─────────────────────────────────────────────────────

    async def _online_host(self)->None:
        if self._connecting: return
        self._connecting=True
        try:
            self.net_status="Connecting…"; self.net_status_c=TXT_DIM
            nm=NetworkManager()
            ok=await nm.connect(self.url_input.text)
            if not ok:
                self.net_status=f"Error: {nm.error}"; self.net_status_c=TXT_ERR
                return
            nm.send({"t":"create"})
            # wait for response
            for _ in range(100):
                await asyncio.sleep(0.05)
                msg=nm.recv()
                if msg:
                    if msg.get("t")=="ok" and msg.get("role")=="host":
                        self.net=nm; self.online_role="host"
                        self.online_code=msg["code"]
                        self.online_sub="waiting"
                        self.net_status=""; self.net_status_c=TXT_DIM
                        # Copy code to clipboard
                        _clipboard_set(msg['code'].upper())
                        break
                    else:
                        self.net_status="Unexpected server response"; self.net_status_c=TXT_ERR
                        break
            else:
                self.net_status="Server timeout"; self.net_status_c=TXT_ERR
        finally:
            self._connecting=False

    async def _online_join(self, code:str)->None:
        if self._connecting: return
        self._connecting=True
        try:
            self.net_status=f"Connecting to '{code}'…"; self.net_status_c=TXT_DIM
            nm=NetworkManager()
            ok=await nm.connect(self.url_input.text)
            if not ok:
                self.net_status=f"Error: {nm.error}"; self.net_status_c=TXT_ERR
                return
            nm.send({"t":"join","code":code})
            for _ in range(100):
                await asyncio.sleep(0.05)
                msg=nm.recv()
                if msg:
                    if msg.get("t")=="ok" and msg.get("role")=="guest":
                        self.net=nm; self.online_role="guest"
                        self.online_code=code; self.online_sub="joining"
                        self.net_status="Connected! Waiting for host to start…"
                        self.net_status_c=TXT_OK
                        break
                    elif msg.get("t")=="err":
                        self.net_status=f"Error: {msg.get('msg','?')}"; self.net_status_c=TXT_ERR
                        break
            else:
                self.net_status="Server timeout"; self.net_status_c=TXT_ERR
        finally:
            self._connecting=False


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP  (asyncio-compatible — works with Pyodide)
# ═════════════════════════════════════════════════════════════════════════════

async def main()->None:
    game    = Game()
    running = True

    while running:
        dt = min(clock.tick(FPS)/1000.0, 0.050)

        for ev in pygame.event.get():
            if not game.handle_event(ev):
                running=False; break

        game.update(dt)
        game.draw()
        await asyncio.sleep(0)

    if game.net:
        await game.net.close()
    pygame.quit()
    sys.exit(0)


if __name__=="__main__":
    asyncio.run(main())

