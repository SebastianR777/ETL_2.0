
import re
import json
from datetime import datetime, date
from pathlib import Path

HOY = date.today()

# ──────────────────────────────────────────────
# 1. Parseo de fechas
# ──────────────────────────────────────────────

FORMATOS_FECHA = [
    (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", "YMD"),
    (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", "DMY"),
]


def parsear_fecha(texto: str):
    texto = texto.strip()
    if re.search(r"a\.?c\.?|alrededor", texto, re.I):
        return None
    for patron, orden in FORMATOS_FECHA:
        m = re.search(patron, texto)
        if m:
            g = m.groups()
            anio, mes, dia = (int(g[0]), int(g[1]), int(g[2])) if orden == "YMD" \
                else (int(g[2]), int(g[1]), int(g[0]))
            if 1 <= mes <= 12 and 1 <= dia <= 31 and 1000 <= anio <= 2100:
                return dia, mes, anio
    return None


def calcular_edad(dia: int, mes: int, anio: int):
    try:
        nacimiento = date(anio, mes, dia)
        edad = HOY.year - nacimiento.year
        if (HOY.month, HOY.day) < (nacimiento.month, nacimiento.day):
            edad -= 1
        return edad
    except ValueError:
        return None


def es_cumpleanios_hoy(dia: int, mes: int) -> bool:
    return HOY.day == dia and HOY.month == mes


# ──────────────────────────────────────────────
# 2. API Celebrities (caché en archivo)
# ──────────────────────────────────────────────

CACHE_IMAGENES_PATH = Path("output") / "celebrities_cache.json"


def cargar_cache_imagenes() -> dict:
    if CACHE_IMAGENES_PATH.exists():
        try:
            return json.loads(CACHE_IMAGENES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_cache_imagenes(cache: dict):
    CACHE_IMAGENES_PATH.parent.mkdir(exist_ok=True)
    CACHE_IMAGENES_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def buscar_imagen_famoso(nombre: str, cache: dict) -> dict | None:
    """
    Busca la imagen de un famoso en la Celebrities API by APIRobots.
    Guarda en caché para no repetir llamadas.
    Devuelve dict con {img, fuente, capturedAt} o None.
    """
    key = nombre.lower().strip()
    if key in cache:
        return cache[key]

    try:
        import urllib.request
        import urllib.parse

        headers = {
            "x-atd-key": "NSI9DVBVa34hf6uRTvvmYKDaAvXsPvB5OkS4dHNbuesEIXvXaS",
            "x-apihub-host": "Celebrities-API-by-APIRobots.allthingsdev.co",
            "x-apihub-endpoint": "e2b3495b-b9a8-431e-b4af-bbff954b16e5",
        }
        url = (
            "https://Celebrities-API-by-APIRobots.proxy-production.allthingsdev.co"
            f"/v1/celebrities?name={urllib.parse.quote(nombre)}&page=1"
        )
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        celebs = data if isinstance(data, list) else (
            data.get("celebrities") or data.get("data") or data.get("results") or []
        )
        if not celebs:
            cache[key] = None
            return None

        c = celebs[0]
        img = (
            c.get("image") or c.get("photo") or c.get("picture")
            or c.get("thumbnail") or c.get("img") or c.get("profile_image")
        )
        result = {
            "img": img,
            "fuente": "Celebrities API by APIRobots",
            "capturedAt": c.get("updated_at") or c.get("created_at") or datetime.now().isoformat(),
            "nombre_api": c.get("name", nombre),
        }
        cache[key] = result
        return result

    except Exception as e:
        print(f"   ⚠  API error para '{nombre}': {e}")
        cache[key] = None
        return None


# ──────────────────────────────────────────────
# 3. Procesamiento principal
# ──────────────────────────────────────────────

def procesar_famosos(ruta_archivo: str | Path, enriquecer_api: bool = False) -> dict:
    """
    Lee el archivo de famosos y normaliza.
    Si enriquecer_api=True, consulta la Celebrities API para cada registro.
    """
    lineas = Path(ruta_archivo).read_text(encoding="utf-8", errors="replace").splitlines()
    lineas = [l.strip() for l in lineas if l.strip()]

    cambios = []
    errores = []
    vistos = {}
    registros = []

    cache_img = cargar_cache_imagenes() if enriquecer_api else {}

    for i, linea in enumerate(lineas, 1):
        partes = re.split(r"^\d+\.\s*", linea, maxsplit=1)
        contenido = partes[-1].strip()

        if " - " not in contenido:
            errores.append({"linea": i, "contenido": linea, "motivo": "Sin separador ' - '"})
            continue

        nombre_raw, fecha_raw = contenido.split(" - ", 1)
        nombre_raw = nombre_raw.strip()
        fecha_raw = fecha_raw.strip()

        fecha_parsed = parsear_fecha(fecha_raw)
        if fecha_parsed is None:
            fecha_normalizada = fecha_raw
            edad = None
            flag_cumple = False
        else:
            dia, mes, anio = fecha_parsed
            fecha_normalizada = f"{dia:02d}-{mes:02d}-{anio}"
            edad = calcular_edad(dia, mes, anio)
            flag_cumple = es_cumpleanios_hoy(dia, mes)

        clave = (nombre_raw.lower(), fecha_normalizada.lower())
        if clave in vistos:
            cambios.append({
                "linea": i, "original": linea,
                "accion": f"DUPLICADO de línea {vistos[clave]}, eliminado"
            })
            continue
        vistos[clave] = i

        if fecha_raw != fecha_normalizada and fecha_parsed is not None:
            cambios.append({
                "linea": i, "original": linea,
                "accion": f"Fecha normalizada: '{fecha_raw}' → '{fecha_normalizada}'"
            })

        registro = {
            "nombre": nombre_raw,
            "fecha_nacimiento": fecha_normalizada,
            "edad": edad,
            "es_cumpleanios": flag_cumple,
        }

        # Enriquecer con imagen de la API (opcional)
        if enriquecer_api:
            img_data = buscar_imagen_famoso(nombre_raw, cache_img)
            registro["imagen"] = img_data.get("img") if img_data else None
            registro["imagen_fuente"] = img_data.get("fuente") if img_data else None
            registro["imagen_fecha_captura"] = img_data.get("capturedAt") if img_data else None

        registros.append(registro)

    if enriquecer_api:
        guardar_cache_imagenes(cache_img)

    stats = {
        "leidos": len(lineas),
        "procesados": len(registros),
        "duplicados": len(lineas) - len(registros) - len(errores),
        "errores": len(errores),
        "cumpleanios": sum(1 for r in registros if r["es_cumpleanios"]),
    }

    return {"registros": registros, "stats": stats, "cambios": cambios, "errores": errores}


# ──────────────────────────────────────────────
# 4. Exportar JSON
# ──────────────────────────────────────────────

def exportar_json_famosos(resultado: dict, ruta_salida: str | Path) -> Path:
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(exist_ok=True)
    exportacion = {
        "coleccion": "famosos",
        "timestamp": datetime.now().isoformat(),
        "stats": resultado["stats"],
        "registros": resultado["registros"],
    }
    ruta_salida.write_text(
        json.dumps(exportacion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ruta_salida


# ──────────────────────────────────────────────
# 5. Guardar en Firebase (opcional)
# ──────────────────────────────────────────────

def guardar_en_firebase(resultado: dict, firebase_config: dict | None = None):
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        print("⚠  firebase-admin no instalado. Ejecute: pip install firebase-admin")
        return False

    if not firebase_admin._apps:
        cred = (
            credentials.Certificate(firebase_config["credential_path"])
            if firebase_config and "credential_path" in firebase_config
            else credentials.ApplicationDefault()
        )
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    col = db.collection("famosos")
    for doc in col.stream():
        doc.reference.delete()

    batch = db.batch()
    count = 0
    for registro in resultado["registros"]:
        doc_ref = col.document()
        batch.set(doc_ref, registro)
        count += 1
        if count % 500 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"✅ {count} registros guardados en Firestore (colección 'famosos')")
    return True


# ──────────────────────────────────────────────
# 6. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("famosos_prueba.txt")
    usar_api = "--api" in sys.argv

    if not ruta.exists():
        print(f"Archivo no encontrado: {ruta}")
        sys.exit(1)

    print(f"Procesando: {ruta}")
    if usar_api:
        print("Modo enriquecimiento API activado (--api)")

    resultado = procesar_famosos(ruta, enriquecer_api=usar_api)

    s = resultado["stats"]
    print(f"\n📊 Estadísticas:")
    print(f"   Leídos      : {s['leidos']}")
    print(f"   Procesados  : {s['procesados']}")
    print(f"   Duplicados  : {s['duplicados']}")
    print(f"   Errores     : {s['errores']}")
    print(f"   Cumpleaños  : {s['cumpleanios']}")

    salida = Path("output") / "famosos_normalizados.json"
    exportar_json_famosos(resultado, salida)
    print(f"\n💾 JSON exportado: {salida}")

    print("\n🔍 Primeros 5 registros normalizados:")
    for r in resultado["registros"][:5]:
        cumple = "🎂" if r["es_cumpleanios"] else ""
        edad_str = f"{r['edad']} años" if r["edad"] is not None else "—"
        print(f"   {r['nombre']:35} | {r['fecha_nacimiento']} | {edad_str} {cumple}")

    if resultado["cambios"]:
        print(f"\n📝 Cambios realizados ({len(resultado['cambios'])}):")
        for c in resultado["cambios"][:10]:
            print(f"   L{c['linea']:>4} | {c['accion']}")

    print("\nUso con enriquecimiento API:")
    print(f"  python {Path(__file__).name} {ruta} --api")
