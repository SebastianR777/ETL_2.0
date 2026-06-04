
import re
import json
from datetime import datetime
from pathlib import Path


# ──────────────────────────────────────────────
# 1. Parseo de dirección
# ──────────────────────────────────────────────

def parsear_direccion(direccion_raw: str) -> dict:
    """
    Divide una dirección libre en sus componentes:
      nombre_calle, numero_calle, ciudad_estado_provincia, pais.
    """
    if not direccion_raw or direccion_raw.strip().lower() in ("", "n/a", "-"):
        return {
            "nombre_calle": "",
            "numero_calle": "",
            "ciudad_estado_provincia": "",
            "pais": "",
        }

    partes = [p.strip() for p in direccion_raw.split(",") if p.strip()]
    pais = partes[-1] if len(partes) >= 1 else ""
    ciudad_estado = partes[-2] if len(partes) >= 2 else ""
    fragmento_calle = ", ".join(partes[:-2]) if len(partes) > 2 else ""

    numero_match = re.search(r"\b(\d+[A-Za-z]?)\b", fragmento_calle)
    numero_calle = numero_match.group(1) if numero_match else ""
    nombre_calle = (
        re.sub(r"\b" + re.escape(numero_calle) + r"\b", "", fragmento_calle).strip(" ,.-")
        if numero_calle else fragmento_calle.strip()
    )

    return {
        "nombre_calle": nombre_calle,
        "numero_calle": numero_calle,
        "ciudad_estado_provincia": ciudad_estado,
        "pais": pais,
    }


def parsear_georef(georef_raw: str) -> dict | None:
    """Extrae latitud y longitud de 'lat, lon'. Devuelve None si no es parseable."""
    m = re.match(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$", georef_raw.strip())
    if m:
        return {"latitud": float(m.group(1)), "longitud": float(m.group(2))}
    return None


# ──────────────────────────────────────────────
# 2. Procesamiento principal
# ──────────────────────────────────────────────

def procesar_lugares(ruta_archivo: str | Path) -> dict:
    """
    Lee el archivo de lugares (formato: Nombre;Dirección;Lat,Lon) y devuelve:
      - lugares:        lista de {id, nombre}
      - georeferencias: lista de {lugar_id, nombre, latitud, longitud}
      - direcciones:    lista de {lugar_id, nombre, nombre_calle, numero_calle,
                                  ciudad_estado_provincia, pais}
      - stats, duplicados, errores
    """
    lineas = Path(ruta_archivo).read_text(encoding="utf-8", errors="replace").splitlines()
    lineas = [l.strip() for l in lineas if l.strip()]

    # Saltar cabecera si existe
    if lineas and "Nombre del lugar" in lineas[0]:
        lineas = lineas[1:]

    errores    = []
    duplicados = []
    vistos_clave = {}

    lugares        = []
    georeferencias = []
    direcciones    = []
    id_counter     = 1

    for i, linea in enumerate(lineas, 2):
        columnas = linea.split(";")

        if len(columnas) < 3:
            errores.append({"linea": i, "contenido": linea, "motivo": "Menos de 3 columnas"})
            continue

        nombre_raw    = columnas[0].strip()
        direccion_raw = columnas[1].strip()
        georef_raw    = columnas[2].strip()

        nombre = re.sub(r"[\x00-\x1f\x7f]", "", nombre_raw).strip()
        if not nombre:
            errores.append({"linea": i, "contenido": linea, "motivo": "Nombre vacío"})
            continue

        clave = (nombre.lower(), georef_raw.lower())
        if clave in vistos_clave:
            duplicados.append({
                "linea": i,
                "nombre": nombre,
                "duplica_a": vistos_clave[clave],
            })
            continue
        vistos_clave[clave] = i

        georef = parsear_georef(georef_raw)
        if georef is None:
            errores.append({
                "linea": i, "contenido": linea,
                "motivo": f"Georef inválida: '{georef_raw}'"
            })
            georef = {"latitud": None, "longitud": None}

        direccion = parsear_direccion(direccion_raw)
        lugar_id  = f"lugar_{id_counter:04d}"
        id_counter += 1

        lugares.append({"id": lugar_id, "nombre": nombre})
        georeferencias.append({"lugar_id": lugar_id, "nombre": nombre, **georef})
        direcciones.append({"lugar_id": lugar_id, "nombre": nombre, **direccion})

    stats = {
        "leidos": len(lineas),
        "unicos": len(lugares),
        "duplicados": len(duplicados),
        "errores": len(errores),
    }

    return {
        "lugares": lugares,
        "georeferencias": georeferencias,
        "direcciones": direcciones,
        "stats": stats,
        "duplicados": duplicados,
        "errores": errores,
    }


# ──────────────────────────────────────────────
# 3. Exportar JSON
# ──────────────────────────────────────────────

def exportar_json_lugares(resultado: dict, ruta_salida: str | Path) -> Path:
    """Guarda las tres colecciones como JSON."""
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(exist_ok=True)

    exportacion = {
        "timestamp": datetime.now().isoformat(),
        "stats": resultado["stats"],
        "colecciones": {
            "lugares":        resultado["lugares"],
            "georeferencias": resultado["georeferencias"],
            "direcciones":    resultado["direcciones"],
        },
    }
    ruta_salida.write_text(
        json.dumps(exportacion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ruta_salida


# ──────────────────────────────────────────────
# 4. Exportar GeoJSON (para Leaflet / mapas)
# ──────────────────────────────────────────────

def exportar_geojson(resultado: dict, ruta_salida: str | Path) -> Path:
    """
    Genera un GeoJSON estándar con todos los lugares que tienen coordenadas.
    Compatible con Leaflet, QGIS, etc.
    """
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(exist_ok=True)

    features = []
    dir_map = {d["lugar_id"]: d for d in resultado["direcciones"]}

    for g in resultado["georeferencias"]:
        if g["latitud"] is None or g["longitud"] is None:
            continue
        d = dir_map.get(g["lugar_id"], {})
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [g["longitud"], g["latitud"]],  # GeoJSON: [lon, lat]
            },
            "properties": {
                "lugar_id": g["lugar_id"],
                "nombre":   g["nombre"],
                "pais":     d.get("pais", ""),
                "ciudad":   d.get("ciudad_estado_provincia", ""),
                "calle":    d.get("nombre_calle", ""),
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }
    ruta_salida.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
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

    def subir_coleccion(registros: list, col_name: str):
        col = db.collection(col_name)
        for doc in col.stream():
            doc.reference.delete()
        batch = db.batch()
        count = 0
        for registro in registros:
            doc_id  = registro.get("id") or registro.get("lugar_id") or None
            doc_ref = col.document(doc_id) if doc_id else col.document()
            batch.set(doc_ref, registro)
            count += 1
            if count % 500 == 0:
                batch.commit()
                batch = db.batch()
        batch.commit()
        print(f"   ✅ {count} documentos → colección '{col_name}'")

    print("Subiendo a Firestore…")
    subir_coleccion(resultado["lugares"],        "lugares")
    subir_coleccion(resultado["georeferencias"], "georeferencias")
    subir_coleccion(resultado["direcciones"],    "direcciones")
    return True


# ──────────────────────────────────────────────
# 6. Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("DATOS2026-3.TXT")
    if not ruta.exists():
        print(f"Archivo no encontrado: {ruta}")
        sys.exit(1)

    print(f"Procesando: {ruta}")
    resultado = procesar_lugares(ruta)

    s = resultado["stats"]
    print(f"\n📊 Estadísticas:")
    print(f"   Leídos      : {s['leidos']}")
    print(f"   Únicos      : {s['unicos']}")
    print(f"   Duplicados  : {s['duplicados']}")
    print(f"   Errores     : {s['errores']}")

    salida_json    = Path("output") / "lugares_normalizados.json"
    salida_geojson = Path("output") / "lugares_normalizados.geojson"
    exportar_json_lugares(resultado, salida_json)
    exportar_geojson(resultado, salida_geojson)
    print(f"\n💾 JSON exportado: {salida_json}")
    print(f"💾 GeoJSON exportado: {salida_geojson}")

   

    print("\n🗺  Primeros 5 lugares:")
    for idx, l in enumerate(resultado["lugares"][:5]):
        g = resultado["georeferencias"][idx]
        d = resultado["direcciones"][idx]
        print(f"   {l['nombre']:40} | lat={g['latitud']}, lon={g['longitud']}")
        print(f"   {'':42} {d['ciudad_estado_provincia']} | {d['pais']}")

    if resultado["duplicados"]:
        print(f"\n🔁 Duplicados eliminados ({len(resultado['duplicados'])}):")
        for dup in resultado["duplicados"][:5]:
            print(f"   L{dup['linea']:>4} | {dup['nombre']} (duplica L{dup['duplica_a']})")
