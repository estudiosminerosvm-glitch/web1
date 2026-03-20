#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║  MINERALBOARD — Scraper de Precios + Actualización Google Sheets║
║  MPPDEMIB — Dirección General de Evaluación Económica           ║
║                                                                  ║
║  ESTE SCRIPT CORRE EN TU PC Y HACE:                             ║
║  1. Descarga precios reales de Investing.com (scraping)         ║
║  2. Descarga de APIs gratuitas (metals.dev, metalpriceapi)      ║
║  3. Descarga de FRED (Reserva Federal EE.UU.)                  ║
║  4. Convierte TODO a USD/kg                                     ║
║  5. Sube los precios a Google Sheets automáticamente            ║
║  6. Repite cada N segundos                                      ║
║                                                                  ║
║  INSTALACIÓN:                                                    ║
║    pip install requests beautifulsoup4 gspread google-auth       ║
║                                                                  ║
║  USO:                                                            ║
║    python scraper_minerales.py                  # cada 60s       ║
║    python scraper_minerales.py --intervalo 30   # cada 30s       ║
║    python scraper_minerales.py --solo-csv       # sin Sheets     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import requests
import time
import sys
import os
import csv
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

# ================================================================
# CONFIGURACIÓN — EDITAR AQUÍ
# ================================================================

# Google Sheets: necesitas un Service Account (ver README)
GOOGLE_CREDENTIALS = 'credentials.json'     # Archivo JSON del Service Account
SPREADSHEET_ID = ''                          # ID de tu Google Sheet (lo de la URL entre /d/ y /edit)
HOJA_NOMBRE = 'Datos'                        # Nombre de la hoja

# APIs gratuitas (opcionales — mejoran la precisión)
# Regístrate gratis en cada una y pon tu key aquí
METALS_DEV_KEY = ''        # https://metals.dev (100 req/mes)
METALPRICEAPI_KEY = ''     # https://metalpriceapi.com (100 req/mes)
GOLDAPI_KEY = ''           # https://goldapi.io (360 req/mes)

# Archivos de salida
CSV_SALIDA = 'precios_minerales.csv'
JSON_SALIDA = 'precios_minerales.json'

# ================================================================
# FACTORES DE CONVERSIÓN
# ================================================================
TROY_OZ_A_KG = 32.1507     # 1 kg = 32.1507 troy oz
LB_A_KG = 2.20462          # 1 kg = 2.20462 libras
MT_A_KG = 0.001            # 1 metric ton = 1000 kg

# ================================================================
# 10 MINERALES (sin duplicados, precios EE.UU.)
# ================================================================
MINERALES = {
    'Oro':       {'sym':'Au','col':'B','unit':'troy_oz','exchange':'COMEX', 'fallback':4586.41, 'factor':TROY_OZ_A_KG},
    'Plata':     {'sym':'Ag','col':'C','unit':'troy_oz','exchange':'COMEX', 'fallback':69.66,   'factor':TROY_OZ_A_KG},
    'Cobre':     {'sym':'Cu','col':'D','unit':'lb',     'exchange':'COMEX', 'fallback':5.4558,  'factor':LB_A_KG},
    'Aluminio':  {'sym':'Al','col':'E','unit':'mt',     'exchange':'LME',   'fallback':3251.15, 'factor':MT_A_KG},
    'Niquel':    {'sym':'Ni','col':'F','unit':'mt',     'exchange':'LME',   'fallback':16921.0, 'factor':MT_A_KG},
    'Zinc':      {'sym':'Zn','col':'G','unit':'mt',     'exchange':'LME',   'fallback':3080.75, 'factor':MT_A_KG},
    'Estaño':    {'sym':'Sn','col':'H','unit':'mt',     'exchange':'LME',   'fallback':46625.0, 'factor':MT_A_KG},
    'Plomo':     {'sym':'Pb','col':'I','unit':'mt',     'exchange':'LME',   'fallback':1887.65, 'factor':MT_A_KG},
    'Platino':   {'sym':'Pt','col':'J','unit':'troy_oz','exchange':'NYMEX', 'fallback':1928.15, 'factor':TROY_OZ_A_KG},
    'Paladio':   {'sym':'Pd','col':'K','unit':'troy_oz','exchange':'NYMEX', 'fallback':1448.00, 'factor':TROY_OZ_A_KG},
}

# ================================================================
# LOGGING
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler('scraper.log', encoding='utf-8')]
)
log = logging.getLogger('Scraper')

# ================================================================
# FUNCIONES DE DESCARGA
# ================================================================

def convertir_a_usd_kg(precio_raw, tipo_unidad, factor):
    """Convierte precio en unidad original → USD/kg"""
    return round(precio_raw * factor, 6)


def descargar_investing():
    """
    FUENTE 1: Scraping de Investing.com — página de metales
    Retorna dict {nombre_mineral: precio_raw_en_unidad_original}
    """
    precios = {}
    try:
        from bs4 import BeautifulSoup
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Accept': 'text/html,application/xhtml+xml',
        }
        
        # Página de futuros de metales
        urls = [
            'https://es.investing.com/commodities/metals',
            'https://www.investing.com/commodities/metals',
        ]
        
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Buscar tabla de precios
                filas = soup.select('table tbody tr')
                if not filas:
                    filas = soup.select('tr[data-test]') or soup.select('.datatable-v2 tbody tr')
                
                mapeo = {
                    'oro': 'Oro', 'gold': 'Oro',
                    'plata': 'Plata', 'silver': 'Plata',
                    'cobre': 'Cobre', 'copper': 'Cobre',
                    'aluminio': 'Aluminio', 'aluminum': 'Aluminio',
                    'niquel': 'Niquel', 'níquel': 'Niquel', 'nickel': 'Niquel',
                    'zinc': 'Zinc',
                    'estaño': 'Estaño', 'tin': 'Estaño',
                    'plomo': 'Plomo', 'lead': 'Plomo',
                    'platino': 'Platino', 'platinum': 'Platino',
                    'paladio': 'Paladio', 'palladium': 'Paladio',
                }
                
                for fila in filas:
                    try:
                        celdas = fila.select('td')
                        if len(celdas) < 3:
                            continue
                        
                        nombre_texto = celdas[0].get_text(strip=True).lower()
                        precio_texto = celdas[1].get_text(strip=True) if len(celdas) > 1 else ''
                        
                        # Parsear nombre
                        mineral_encontrado = None
                        for clave, nombre in mapeo.items():
                            if clave in nombre_texto:
                                mineral_encontrado = nombre
                                break
                        
                        if not mineral_encontrado:
                            continue
                        
                        # Si ya tenemos este mineral, saltar (evitar duplicados)
                        if mineral_encontrado in precios:
                            continue
                        
                        # Parsear precio (formato español: 3.251,15 o inglés: 3251.15)
                        precio_texto = precio_texto.replace(' ', '')
                        if '.' in precio_texto and ',' in precio_texto:
                            if precio_texto.rindex(',') > precio_texto.rindex('.'):
                                precio_texto = precio_texto.replace('.', '').replace(',', '.')
                            else:
                                precio_texto = precio_texto.replace(',', '')
                        elif ',' in precio_texto:
                            precio_texto = precio_texto.replace(',', '.')
                        
                        precio_raw = float(precio_texto)
                        precios[mineral_encontrado] = precio_raw
                        
                    except (ValueError, IndexError):
                        continue
                
                if precios:
                    log.info(f'✅ Investing.com: {len(precios)} minerales descargados')
                    break  # Si una URL funcionó, no intentar la otra
                    
            except Exception as e:
                log.debug(f'Investing.com URL {url}: {e}')
                continue
    
    except ImportError:
        log.warning('beautifulsoup4 no instalado. Ejecutar: pip install beautifulsoup4')
    except Exception as e:
        log.error(f'❌ Error Investing.com: {e}')
    
    return precios


def descargar_fred():
    """
    FUENTE 2: FRED (Federal Reserve Economic Data) — datos gratuitos sin API key
    """
    precios = {}
    
    series = {
        'Oro':       'GOLDAMGBD228NLBM',   # USD/troy oz
        'Plata':     'SLVPRUSD',            # USD/troy oz  
        'Cobre':     'PCOPPUSDM',           # USD/metric ton
        'Aluminio':  'PALUMUSDM',           # USD/metric ton
        'Niquel':    'PNICKUSDM',           # USD/metric ton
        'Zinc':      'PZINCUSDM',           # USD/metric ton
        'Estaño':    'PTINUSDM',            # USD/metric ton
    }
    
    for mineral, serie_id in series.items():
        try:
            url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie_id}'
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            
            lineas = resp.text.strip().split('\n')
            # Último valor válido (de atrás hacia adelante)
            for linea in reversed(lineas[1:]):
                partes = linea.split(',')
                if len(partes) >= 2:
                    try:
                        valor = float(partes[1])
                        if valor > 0:
                            # FRED retorna en unidades diferentes según la serie
                            if mineral in ('Oro', 'Plata'):
                                precios[mineral] = valor  # ya en USD/troy oz
                            else:
                                # FRED metals están en USD/mt, necesitamos convertir
                                # pero el factor es diferente porque son mt no lb
                                # Guardamos el raw y la conversión se hace después
                                info = MINERALES[mineral]
                                if info['unit'] == 'mt':
                                    precios[mineral] = valor  # USD/mt raw
                                elif info['unit'] == 'lb':
                                    precios[mineral] = valor / 1000 * LB_A_KG  # aprox
                            break
                    except ValueError:
                        continue
            
            time.sleep(0.5)  # No saturar FRED
            
        except Exception as e:
            log.debug(f'FRED {mineral}: {e}')
    
    if precios:
        log.info(f'✅ FRED: {len(precios)} minerales descargados')
    
    return precios


def descargar_metals_dev():
    """FUENTE 3: Metals.dev API (100 req/mes gratis)"""
    if not METALS_DEV_KEY:
        return {}
    
    precios = {}
    try:
        url = f'https://api.metals.dev/v1/latest?api_key={METALS_DEV_KEY}&currency=USD'
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return {}
        
        data = resp.json()
        metals = data.get('metals', {})
        
        mapeo_api = {
            'gold': 'Oro', 'silver': 'Plata', 'copper': 'Cobre',
            'aluminum': 'Aluminio', 'nickel': 'Niquel', 'zinc': 'Zinc',
            'tin': 'Estaño', 'lead': 'Plomo', 'platinum': 'Platino', 'palladium': 'Paladio',
        }
        
        for api_name, mineral_name in mapeo_api.items():
            if api_name in metals:
                precios[mineral_name] = metals[api_name]  # USD/troy oz o USD/mt
        
        if precios:
            log.info(f'✅ Metals.dev: {len(precios)} minerales')
    except Exception as e:
        log.error(f'❌ Metals.dev: {e}')
    
    return precios


def descargar_metalpriceapi():
    """FUENTE 4: MetalpriceAPI (100 req/mes gratis)"""
    if not METALPRICEAPI_KEY:
        return {}
    
    precios = {}
    try:
        symbols = 'XAU,XAG,XPT,XPD,XCU,ALU'
        url = f'https://api.metalpriceapi.com/v1/latest?api_key={METALPRICEAPI_KEY}&base=USD&currencies={symbols}'
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return {}
        
        rates = resp.json().get('rates', {})
        mapeo = {'XAU':'Oro','XAG':'Plata','XPT':'Platino','XPD':'Paladio'}
        
        for sym, nombre in mapeo.items():
            rate = rates.get(sym)
            if rate and rate > 0:
                precios[nombre] = 1.0 / rate  # API retorna inverso
        
        if precios:
            log.info(f'✅ MetalpriceAPI: {len(precios)} minerales')
    except Exception as e:
        log.error(f'❌ MetalpriceAPI: {e}')
    
    return precios


# ================================================================
# MOTOR PRINCIPAL — COMBINA TODAS LAS FUENTES
# ================================================================
def obtener_todos_los_precios():
    """
    Intenta todas las fuentes en orden de prioridad.
    Retorna {mineral: precio_usd_kg}
    """
    log.info('═' * 55)
    log.info(f'🔄 DESCARGANDO — {datetime.now().strftime("%H:%M:%S")}')
    log.info('═' * 55)
    
    # Recolectar de todas las fuentes
    fuentes = [
        ('Investing.com', descargar_investing),
        ('FRED',          descargar_fred),
        ('Metals.dev',    descargar_metals_dev),
        ('MetalpriceAPI', descargar_metalpriceapi),
    ]
    
    precios_raw = {}      # {mineral: (precio_raw, fuente)}
    
    for nombre_fuente, funcion in fuentes:
        try:
            resultado = funcion()
            for mineral, precio in resultado.items():
                if mineral not in precios_raw and mineral in MINERALES:
                    precios_raw[mineral] = (precio, nombre_fuente)
        except Exception as e:
            log.error(f'Error en {nombre_fuente}: {e}')
    
    # Convertir a USD/kg y llenar faltantes con fallback
    precios_kg = {}
    
    log.info(f'\n{"Mineral":<12} {"Raw":>12} {"Fuente":<16} {"USD/kg":>14}')
    log.info('-' * 58)
    
    for mineral, info in MINERALES.items():
        if mineral in precios_raw:
            raw, fuente = precios_raw[mineral]
            usd_kg = convertir_a_usd_kg(raw, info['unit'], info['factor'])
            marker = '✅'
        else:
            raw = info['fallback']
            fuente = 'Fallback'
            usd_kg = convertir_a_usd_kg(raw, info['unit'], info['factor'])
            marker = '⚠️'
        
        precios_kg[mineral] = usd_kg
        log.info(f'{marker} {mineral:<10} {raw:>12,.2f} {fuente:<16} {usd_kg:>14,.4f}')
    
    log.info(f'\n📊 Total: {sum(1 for m in precios_raw if m in MINERALES)} de fuentes reales, '
             f'{sum(1 for m in MINERALES if m not in precios_raw)} de fallback')
    
    return precios_kg


# ================================================================
# GOOGLE SHEETS — SUBIR PRECIOS
# ================================================================
def actualizar_sheets(precios_kg):
    """Sube precios a Google Sheets."""
    if not SPREADSHEET_ID:
        log.warning('⚠️ SPREADSHEET_ID vacío — no se actualizó Sheets')
        return False
    
    if not Path(GOOGLE_CREDENTIALS).exists():
        log.warning(f'⚠️ {GOOGLE_CREDENTIALS} no encontrado')
        log.info('   Para configurar Google Sheets:')
        log.info('   1. Ve a console.cloud.google.com')
        log.info('   2. Crea proyecto → Habilita Sheets API + Drive API')
        log.info('   3. Crea Service Account → Descarga JSON → renombra a credentials.json')
        log.info('   4. Comparte tu Sheet con el email del Service Account')
        return False
    
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS,
            scopes=['https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive']
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(HOJA_NOMBRE)
        
        # Buscar fila con año actual o crearla
        datos = ws.get_all_values()
        anio = str(datetime.now().year)
        fila_target = None
        
        for i, fila in enumerate(datos):
            if fila and fila[0].strip() == anio:
                fila_target = i + 1
                break
        
        if not fila_target:
            fila_target = len(datos) + 1
            ws.update_cell(fila_target, 1, int(anio))
        
        # Subir cada precio
        for mineral, info in MINERALES.items():
            precio = precios_kg.get(mineral)
            if precio:
                col_letra = info['col']
                col_num = ord(col_letra) - ord('A') + 1
                ws.update_cell(fila_target, col_num, round(precio, 6))
        
        # Timestamp
        ts_col = ord('L') - ord('A') + 1
        ws.update_cell(fila_target, ts_col, datetime.now().strftime('%H:%M:%S'))
        
        log.info(f'✅ Google Sheets actualizado (fila {fila_target})')
        return True
        
    except ImportError:
        log.error('gspread no instalado. Ejecutar: pip install gspread google-auth')
    except Exception as e:
        log.error(f'❌ Google Sheets: {e}')
    
    return False


# ================================================================
# EXPORTAR CSV/JSON LOCAL
# ================================================================
def exportar_csv(precios_kg):
    """Guarda CSV local."""
    encabezados = ['Mineral', 'Sym', 'USD_kg', 'Exchange', 'Timestamp']
    filas = []
    for mineral, info in MINERALES.items():
        filas.append([
            mineral, info['sym'],
            round(precios_kg.get(mineral, 0), 6),
            info['exchange'],
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ])
    
    with open(CSV_SALIDA, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(encabezados)
        w.writerows(filas)
    log.info(f'📁 CSV: {CSV_SALIDA}')


def exportar_json(precios_kg):
    """Guarda JSON local."""
    data = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'MineralBoard Scraper',
        'unit': 'USD/kg',
        'minerals': {
            mineral: {
                'symbol': info['sym'],
                'price': round(precios_kg.get(mineral, 0), 6),
                'exchange': info['exchange'],
            }
            for mineral, info in MINERALES.items()
        }
    }
    with open(JSON_SALIDA, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f'📁 JSON: {JSON_SALIDA}')


# ================================================================
# DISPLAY EN CONSOLA
# ================================================================
def mostrar_consola(precios_kg, ciclo):
    """Dashboard en consola."""
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')
    
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print()
    print('  ╔═══════════════════════════════════════════════════════╗')
    print('  ║  ⬡ MINERALBOARD — Precios Reales USD/kg              ║')
    print(f'  ║  {ahora}                        #{ciclo:<5}║')
    print('  ╠═══════════════════════════════════════════════════════╣')
    print(f'  ║ {"Mineral":<12} {"Sym":>3}  {"USD/kg":>14}  {"Bolsa":>6}    ║')
    print('  ╠═══════════════════════════════════════════════════════╣')
    
    for mineral, info in MINERALES.items():
        precio = precios_kg.get(mineral, 0)
        if precio >= 1000:
            ps = f'{precio:>14,.2f}'
        elif precio >= 1:
            ps = f'{precio:>14.4f}'
        else:
            ps = f'{precio:>14.6f}'
        print(f'  ║ {mineral:<12} {info["sym"]:>3}  {ps}  {info["exchange"]:>6}    ║')
    
    print('  ╚═══════════════════════════════════════════════════════╝')
    print()


# ================================================================
# MAIN
# ================================================================
def main():
    parser = argparse.ArgumentParser(description='MineralBoard Scraper')
    parser.add_argument('--intervalo', type=int, default=60,
                        help='Segundos entre actualizaciones (default: 60)')
    parser.add_argument('--solo-csv', action='store_true',
                        help='Solo exportar CSV/JSON, no actualizar Sheets')
    parser.add_argument('--una-vez', action='store_true',
                        help='Ejecutar una vez y salir')
    args = parser.parse_args()
    
    log.info('🚀 MineralBoard Scraper iniciando...')
    log.info(f'   Intervalo: {args.intervalo}s')
    log.info(f'   Google Sheets: {"Desactivado" if args.solo_csv else "Activado" if SPREADSHEET_ID else "Sin configurar"}')
    
    ciclo = 0
    
    try:
        while True:
            ciclo += 1
            
            # 1. Descargar precios
            precios = obtener_todos_los_precios()
            
            # 2. Mostrar en consola
            mostrar_consola(precios, ciclo)
            
            # 3. Exportar CSV y JSON
            exportar_csv(precios)
            exportar_json(precios)
            
            # 4. Subir a Google Sheets
            if not args.solo_csv:
                actualizar_sheets(precios)
            
            # 5. ¿Solo una vez?
            if args.una_vez:
                break
            
            # 6. Esperar
            log.info(f'⏳ Próxima actualización en {args.intervalo}s... (Ctrl+C para salir)')
            time.sleep(args.intervalo)
    
    except KeyboardInterrupt:
        log.info('\n👋 Scraper detenido')
        exportar_csv(precios)
        exportar_json(precios)


if __name__ == '__main__':
    main()
