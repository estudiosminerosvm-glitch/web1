/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║  MINERALBOARD — Google Apps Script v5                       ║
 * ║                                                              ║
 * ║  CORRECCIÓN: GOOGLEFINANCE ahora escribe las fórmulas       ║
 * ║  directamente en la columna C, espera 10 seg, lee el        ║
 * ║  valor calculado, y lo reemplaza con el número fijo.        ║
 * ║                                                              ║
 * ║  RESULTADO ESPERADO:                                         ║
 * ║  ✅ Cobre, Al, Ni, Zn, Sn, Pb → FRED                       ║
 * ║  ✅ Oro, Plata, Platino, Paladio → GOOGLEFINANCE            ║
 * ║                                                              ║
 * ║  PASOS:                                                      ║
 * ║  1. Extensiones → Apps Script                                ║
 * ║  2. Borra TODO y pega este código                            ║
 * ║  3. Guarda (Ctrl+S)                                          ║
 * ║  4. Ejecuta: configurarTodo()                                ║
 * ╚══════════════════════════════════════════════════════════════╝
 */

const HOJA = 'Datos';
const COL_RAW = 3;    // Columna C = Último (Raw)
const COL_HORA = 12;  // Columna L = Hora

// ================================================================
// MINERALES — FRED (funcionan perfecto)
// ================================================================
const FRED_MINERALES = {
  'Cobre':    { fila:8,  serie:'PCOPPUSDM',  factorFRED:0.000453592 },  // USD/mt → USD/lb
  'Aluminio': { fila:9,  serie:'PALUMUSDM',  factorFRED:1 },            // USD/mt directo
  'Niquel':   { fila:10, serie:'PNICKUSDM',  factorFRED:1 },
  'Zinc':     { fila:11, serie:'PZINCUSDM',  factorFRED:1 },
  'Estaño':   { fila:12, serie:'PTINUSDM',   factorFRED:1 },
  'Plomo':    { fila:13, serie:'PLEADUSDM',  factorFRED:1 },
};

// ================================================================
// MINERALES — GOOGLEFINANCE (Oro, Plata, Platino, Paladio)
// ================================================================
const GF_MINERALES = {
  'Oro':      { fila:4,  gf:'CURRENCY:XAUUSD' },   // retorna USD/troy oz
  'Plata':    { fila:5,  gf:'CURRENCY:XAGUSD' },
  'Platino':  { fila:6,  gf:'CURRENCY:XPTUSD' },
  'Paladio':  { fila:7,  gf:'CURRENCY:XPDUSD' },
};


// ================================================================
// FUNCIÓN PRINCIPAL
// ================================================================
function actualizarPrecios() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const hoja = ss.getSheetByName(HOJA);
  
  if (!hoja) {
    Logger.log('❌ Hoja "' + HOJA + '" no encontrada');
    return;
  }
  
  Logger.log('🔄 ACTUALIZANDO PRECIOS');
  Logger.log('   ' + new Date().toLocaleString('es-VE'));
  Logger.log('');
  
  let ok = 0, err = 0;
  const hora = Utilities.formatDate(new Date(), 'America/Caracas', 'HH:mm:ss');
  
  // ──────────────────────────────────────
  // PASO 1: FRED (Cobre → Plomo)
  // ──────────────────────────────────────
  Logger.log('── PASO 1: FRED ──');
  
  for (const [nombre, cfg] of Object.entries(FRED_MINERALES)) {
    try {
      const raw = obtenerFRED(cfg.serie);
      if (raw > 0) {
        const valor = Math.round(raw * cfg.factorFRED * 10000) / 10000;
        hoja.getRange(cfg.fila, COL_RAW).setValue(valor);
        hoja.getRange(cfg.fila, COL_HORA).setValue(hora);
        Logger.log('  ✅ ' + nombre + ' (fila ' + cfg.fila + '): ' + valor + ' → Col C');
        ok++;
      }
    } catch (e) {
      Logger.log('  ❌ ' + nombre + ': ' + e.message);
      err++;
    }
    Utilities.sleep(1000);
  }
  
  // ──────────────────────────────────────
  // PASO 2: GOOGLEFINANCE (Oro → Paladio)
  // Estrategia: escribir fórmula en col C,
  // esperar, leer valor, reemplazar con número
  // ──────────────────────────────────────
  Logger.log('');
  Logger.log('── PASO 2: GOOGLEFINANCE ──');
  
  // Guardar valores actuales por si falla
  const backup = {};
  for (const [nombre, cfg] of Object.entries(GF_MINERALES)) {
    backup[nombre] = hoja.getRange(cfg.fila, COL_RAW).getValue();
  }
  
  // Escribir fórmulas GOOGLEFINANCE en columna C
  for (const [nombre, cfg] of Object.entries(GF_MINERALES)) {
    const formula = '=IFERROR(GOOGLEFINANCE("' + cfg.gf + '"),0)';
    hoja.getRange(cfg.fila, COL_RAW).setFormula(formula);
    Logger.log('  📝 ' + nombre + ' (fila ' + cfg.fila + '): fórmula escrita');
  }
  
  // Forzar recálculo
  SpreadsheetApp.flush();
  Logger.log('  ⏳ Esperando 10 segundos para que GOOGLEFINANCE responda...');
  Utilities.sleep(10000);
  
  // Leer valores y reemplazar fórmulas con números
  for (const [nombre, cfg] of Object.entries(GF_MINERALES)) {
    try {
      const celda = hoja.getRange(cfg.fila, COL_RAW);
      const val = celda.getValue();
      
      if (val && typeof val === 'number' && val > 1) {
        // Éxito — reemplazar fórmula con el número
        celda.setValue(Math.round(val * 10000) / 10000);
        hoja.getRange(cfg.fila, COL_HORA).setValue(hora);
        Logger.log('  ✅ ' + nombre + ' (fila ' + cfg.fila + '): $' + val.toFixed(2) + '/oz → Col C');
        ok++;
      } else {
        // Falló — restaurar valor anterior
        celda.setValue(backup[nombre]);
        Logger.log('  ⚠️ ' + nombre + ': retornó ' + val + ' — restaurado valor anterior (' + backup[nombre] + ')');
      }
    } catch (e) {
      // Error — restaurar backup
      hoja.getRange(cfg.fila, COL_RAW).setValue(backup[nombre]);
      Logger.log('  ❌ ' + nombre + ': ' + e.message + ' — restaurado backup');
      err++;
    }
  }
  
  // ──────────────────────────────────────
  // RESUMEN
  // ──────────────────────────────────────
  Logger.log('');
  Logger.log('═══════════════════════════════════════════');
  Logger.log('📊 ' + ok + '/10 actualizados, ' + err + ' errores');
  Logger.log('   Columna F (USD/kg) se recalcula con =C×E');
  Logger.log('   ' + hora);
  Logger.log('═══════════════════════════════════════════');
}


// ================================================================
// OBTENER PRECIO DE FRED
// ================================================================
function obtenerFRED(serieId) {
  const url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=' + serieId;
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  
  if (resp.getResponseCode() !== 200) {
    throw new Error('HTTP ' + resp.getResponseCode());
  }
  
  const lineas = resp.getContentText().trim().split('\n');
  for (let i = lineas.length - 1; i >= 1; i--) {
    const partes = lineas[i].split(',');
    if (partes.length >= 2) {
      const val = parseFloat(partes[1]);
      if (!isNaN(val) && val > 0) return val;
    }
  }
  throw new Error('Sin datos');
}


// ================================================================
// CONFIGURAR (ejecutar UNA VEZ)
// ================================================================
function configurarTodo() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  
  ScriptApp.newTrigger('actualizarPrecios')
    .timeBased()
    .everyHours(1)
    .create();
  
  Logger.log('✅ Trigger: cada 1 hora');
  actualizarPrecios();
}


// ================================================================
// LIMPIAR FILA 15 DEL SCRIPT ANTERIOR
// ================================================================
function limpiarFilaVieja() {
  const hoja = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HOJA);
  if (!hoja) return;
  const datos = hoja.getDataRange().getValues();
  for (let i = datos.length - 1; i >= 14; i--) {
    if (String(datos[i][0]).trim() === '2026') {
      hoja.deleteRow(i + 1);
      Logger.log('🗑️ Fila ' + (i+1) + ' eliminada');
    }
  }
}


// ================================================================
// MENÚ
// ================================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('⬡ MineralBoard')
    .addItem('🔄 Actualizar precios', 'actualizarPrecios')
    .addItem('⚙️ Configurar (1ra vez)', 'configurarTodo')
    .addItem('🗑️ Limpiar fila vieja', 'limpiarFilaVieja')
    .addToUi();
}
