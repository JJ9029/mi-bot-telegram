import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                sub_inicio TEXT,
                sub_fin TEXT,
                activo INTEGER DEFAULT 0,
                rango TEXT DEFAULT 'miembro',        -- 'admin' | 'ayudante' | 'miembro'
                warns INTEGER DEFAULT 0,
                muted_hasta TEXT,
                nivel_mute INTEGER DEFAULT 0,
                en_canal INTEGER DEFAULT 0,
                en_grupo INTEGER DEFAULT 0,
                aviso_vencimiento_enviado INTEGER DEFAULT 0,
                creado TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS palabras_prohibidas (
                palabra TEXT PRIMARY KEY
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pagos_pendientes (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                solicitado TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS config_texto (
                clave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS invite_links (
                user_id INTEGER,
                tipo TEXT,          -- 'canal' | 'grupo'
                link TEXT,
                usado INTEGER DEFAULT 0,
                creado TEXT
            )
        """)


# ───────────────────────── USUARIOS / SUSCRIPCIÓN ─────────────────────────

def upsert_usuario_basico(user_id, username, first_name):
    with get_db() as db:
        row = db.execute("SELECT user_id FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
        if row:
            db.execute("UPDATE usuarios SET username=?, first_name=? WHERE user_id=?",
                       (username, first_name, user_id))
        else:
            db.execute(
                "INSERT INTO usuarios (user_id, username, first_name, activo, creado) VALUES (?,?,?,0,?)",
                (user_id, username, first_name, datetime.utcnow().isoformat())
            )


def get_usuario(user_id):
    with get_db() as db:
        return db.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,)).fetchone()


def activar_dias(user_id, dias, username=None, first_name=None):
    """Suma días de suscripción. Si ya tenía días activos, se acumulan (no se reemplazan)."""
    ahora = datetime.utcnow()
    with get_db() as db:
        row = db.execute("SELECT * FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
        if row and row["sub_fin"]:
            fin_actual = datetime.fromisoformat(row["sub_fin"])
            base = fin_actual if fin_actual > ahora else ahora
        else:
            base = ahora
        nueva_fin = base + timedelta(days=dias)
        if row:
            db.execute("""
                UPDATE usuarios SET sub_inicio=COALESCE(sub_inicio, ?), sub_fin=?, activo=1,
                       aviso_vencimiento_enviado=0,
                       username=COALESCE(?, username), first_name=COALESCE(?, first_name)
                WHERE user_id=?
            """, (ahora.isoformat(), nueva_fin.isoformat(), username, first_name, user_id))
        else:
            db.execute("""
                INSERT INTO usuarios (user_id, username, first_name, sub_inicio, sub_fin, activo, creado)
                VALUES (?,?,?,?,?,1,?)
            """, (user_id, username, first_name, ahora.isoformat(), nueva_fin.isoformat(), ahora.isoformat()))
        db.execute("DELETE FROM pagos_pendientes WHERE user_id=?", (user_id,))
        return nueva_fin


def restar_dias(user_id, dias):
    with get_db() as db:
        row = db.execute("SELECT sub_fin FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row["sub_fin"]:
            return None
        nueva_fin = datetime.fromisoformat(row["sub_fin"]) - timedelta(days=dias)
        activo = 1 if nueva_fin > datetime.utcnow() else 0
        db.execute("UPDATE usuarios SET sub_fin=?, activo=? WHERE user_id=?",
                   (nueva_fin.isoformat(), activo, user_id))
        return nueva_fin


def dias_restantes(user_id):
    row = get_usuario(user_id)
    if not row or not row["sub_fin"]:
        return 0
    restante = datetime.fromisoformat(row["sub_fin"]) - datetime.utcnow()
    return max(0, restante.days + (1 if restante.seconds > 0 else 0))


def marcar_inactivo(user_id):
    with get_db() as db:
        db.execute("UPDATE usuarios SET activo=0, en_canal=0, en_grupo=0 WHERE user_id=?", (user_id,))


def marcar_membresia(user_id, canal=None, grupo=None):
    with get_db() as db:
        if canal is not None:
            db.execute("UPDATE usuarios SET en_canal=? WHERE user_id=?", (int(canal), user_id))
        if grupo is not None:
            db.execute("UPDATE usuarios SET en_grupo=? WHERE user_id=?", (int(grupo), user_id))


def usuarios_por_vencer(dentro_de_horas):
    limite = datetime.utcnow() + timedelta(hours=dentro_de_horas)
    with get_db() as db:
        return db.execute("""
            SELECT * FROM usuarios WHERE activo=1 AND aviso_vencimiento_enviado=0
            AND sub_fin IS NOT NULL AND sub_fin <= ?
        """, (limite.isoformat(),)).fetchall()


def marcar_aviso_enviado(user_id):
    with get_db() as db:
        db.execute("UPDATE usuarios SET aviso_vencimiento_enviado=1 WHERE user_id=?", (user_id,))


def usuarios_vencidos():
    ahora = datetime.utcnow().isoformat()
    with get_db() as db:
        return db.execute("""
            SELECT * FROM usuarios WHERE activo=1 AND sub_fin IS NOT NULL AND sub_fin < ?
        """, (ahora,)).fetchall()


def usuarios_activos():
    with get_db() as db:
        return db.execute("SELECT * FROM usuarios WHERE activo=1").fetchall()


def todos_los_usuarios():
    with get_db() as db:
        return db.execute("SELECT * FROM usuarios").fetchall()


# ───────────────────────── RANGOS ─────────────────────────

def set_rango(user_id, rango):
    with get_db() as db:
        db.execute("UPDATE usuarios SET rango=? WHERE user_id=?", (rango, user_id))


def get_rango(user_id, admin_id):
    if user_id == admin_id:
        return "admin"
    row = get_usuario(user_id)
    return row["rango"] if row else "miembro"


def get_ayudantes():
    with get_db() as db:
        return db.execute("SELECT * FROM usuarios WHERE rango='ayudante'").fetchall()


# ───────────────────────── ADVERTENCIAS / MUTE ─────────────────────────

def agregar_warn(user_id):
    with get_db() as db:
        db.execute("""
            INSERT INTO usuarios (user_id, warns, creado) VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET warns = warns + 1
        """, (user_id, datetime.utcnow().isoformat()))
        row = db.execute("SELECT warns FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
        return row["warns"]


def reset_warns(user_id):
    with get_db() as db:
        db.execute("UPDATE usuarios SET warns=0, nivel_mute=0 WHERE user_id=?", (user_id,))


def subir_nivel_mute(user_id):
    with get_db() as db:
        row = db.execute("SELECT nivel_mute FROM usuarios WHERE user_id=?", (user_id,)).fetchone()
        nivel = (row["nivel_mute"] if row else 0) + 1
        db.execute("UPDATE usuarios SET nivel_mute=?, warns=0 WHERE user_id=?", (nivel, user_id))
        return nivel


# ───────────────────────── PALABRAS PROHIBIDAS ─────────────────────────

def agregar_palabra(palabra):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO palabras_prohibidas (palabra) VALUES (?)", (palabra.lower(),))


def quitar_palabra(palabra):
    with get_db() as db:
        db.execute("DELETE FROM palabras_prohibidas WHERE palabra=?", (palabra.lower(),))


def listar_palabras():
    with get_db() as db:
        return [r["palabra"] for r in db.execute("SELECT palabra FROM palabras_prohibidas").fetchall()]


# ───────────────────────── PAGOS PENDIENTES ─────────────────────────

def agregar_pago_pendiente(user_id, username):
    with get_db() as db:
        db.execute("""
            INSERT INTO pagos_pendientes (user_id, username, solicitado) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET solicitado=excluded.solicitado
        """, (user_id, username, datetime.utcnow().isoformat()))


def listar_pagos_pendientes():
    with get_db() as db:
        return db.execute("SELECT * FROM pagos_pendientes ORDER BY solicitado").fetchall()


def quitar_pago_pendiente(user_id):
    with get_db() as db:
        db.execute("DELETE FROM pagos_pendientes WHERE user_id=?", (user_id,))


# ───────────────────────── TEXTOS CONFIGURABLES ─────────────────────────

def set_texto(clave, valor):
    with get_db() as db:
        db.execute("""
            INSERT INTO config_texto (clave, valor) VALUES (?,?)
            ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor
        """, (clave, valor))


def get_texto(clave, default=""):
    with get_db() as db:
        row = db.execute("SELECT valor FROM config_texto WHERE clave=?", (clave,)).fetchone()
        return row["valor"] if row else default


# ───────────────────────── STATS ─────────────────────────

def estadisticas():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) c FROM usuarios").fetchone()["c"]
        activos = db.execute("SELECT COUNT(*) c FROM usuarios WHERE activo=1").fetchone()["c"]
        vencidos = db.execute("SELECT COUNT(*) c FROM usuarios WHERE activo=0 AND sub_fin IS NOT NULL").fetchone()["c"]
        pendientes = db.execute("SELECT COUNT(*) c FROM pagos_pendientes").fetchone()["c"]
        return {"total": total, "activos": activos, "vencidos": vencidos, "pendientes": pendientes}
