"""Catálogo de parámetros de los ficheros .nml de SCHISM (param.nml, wwminput.nml, sediment.nml, ice.nml, ...).

Se construye leyendo las plantillas oficiales de schismlab/templates: para cada parámetro guarda la sección,
el valor por defecto y la explicación del propio fichero (comentario en línea y bloque de comentario anterior).
Para los parámetros más importantes hay además una descripción corta en español e inglés (DESC).
La interfaz usa este catálogo para el editor de parámetros; `setup` escribe los ficheros con las
sobreescrituras guardadas en el YAML del caso (`param:` y `namelists:`).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
NAMELISTS = {"param.nml": "param.nml.v5.13", "wwminput.nml": "wwminput.nml.v5.13", "sediment.nml": "sediment.nml.v5.13",
             "ice.nml": "ice.nml.v5.13", "icm.nml": "icm.nml.v5.13", "cosine.nml": "cosine.nml.v5.13"}
# qué módulo compilado exige cada fichero (param.nml siempre)
NAMELIST_MODULE = {"wwminput.nml": "wwm", "sediment.nml": "sed", "ice.nml": "ice", "icm.nml": "icm", "cosine.nml": "cosine"}


@dataclass
class Entry:
    name: str
    section: str
    default: str
    inline: str = ""            # comentario en la misma línea
    block: str = ""             # comentario del bloque anterior
    commented: bool = False     # el parámetro está comentado en la plantilla (opcional)
    modules: list[str] = field(default_factory=list)   # módulos a los que pertenece ([] = núcleo)
    line: int = 0

    @property
    def base(self) -> str:
        """nombre sin índice: iof_hydro(3) -> iof_hydro"""
        return self.name.split("(")[0]

    def help(self, lang: str = "es") -> str:
        d = DESC.get(self.name) or DESC.get(self.base)
        if d:
            return d[0] if lang == "es" else d[1]
        return (self.inline or self.block or "").strip()

    def long_help(self) -> str:
        parts = [p.strip() for p in (self.block, self.inline) if p and p.strip()]
        return "\n".join(parts)


_PARAM = re.compile(r"^\s*(!)?\s*([A-Za-z_]\w*(?:\([\d, ]+\))?)\s*=\s*([^!\n]*?)\s*(?:!(.*))?$")
_SEP = re.compile(r"^!\s*[-+=*]{5,}\s*$")
_MODULE_HINTS = [("wwm", ("USE_WWM", "WWM")), ("sed", ("USE_SED", "SED3D", "sediment")), ("ice", ("USE_ICE", "USE_MICE", "ice module")),
                 ("gen", ("USE_GEN",)), ("age", ("USE_AGE",)), ("eco", ("USE_ECO", "EcoSim")), ("icm", ("USE_ICM",)),
                 ("cosine", ("USE_COSINE", "CoSiNE")), ("marsh", ("USE_MARSH",)), ("ha", ("USE_HA", "harmonic analysis")),
                 ("prec_evap", ("PREC_EVAP",)), ("analysis", ("USE_ANALYSIS",)), ("fib", ("USE_FIB",)), ("dvd", ("USE_DVD",))]
_IOF_MODULE = {"iof_wwm": "wwm", "iof_sed": "sed", "iof_ice": "ice", "iof_gen": "gen", "iof_age": "age", "iof_eco": "eco",
               "iof_icm": "icm", "iof_cos": "cosine", "iof_fib": "fib", "iof_marsh": "marsh", "iof_ana": "analysis", "iof_dvd": "dvd",
               "iof_icm_core": "icm", "iof_icm_silica": "icm", "iof_icm_zb": "icm", "iof_icm_ph": "icm", "iof_icm_srm": "icm",
               "iof_icm_cbp": "icm", "iof_icm_sav": "icm", "iof_icm_marsh": "icm", "iof_icm_sed": "icm", "iof_icm_ba": "icm",
               "iof_icm_clam": "icm", "iof_icm_dbg": "icm", "iof_cos": "cosine"}


def template_path(namelist: str) -> Path:
    return TEMPLATES / NAMELISTS[namelist]


def parse(path: Path, namelist: str = "param.nml") -> list[Entry]:
    entries: list[Entry] = []
    section = ""; block: list[str] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            block = []; continue
        if s.startswith("&"):
            section = s[1:].split()[0].split("!")[0]; block = []; continue
        if s == "/":
            section = ""; block = []; continue
        m = _PARAM.match(line)
        if m and (not m.group(1) or _looks_like_param(m.group(2), m.group(3))):
            commented, name, value, inline = bool(m.group(1)), m.group(2), m.group(3).strip(), (m.group(4) or "").strip()
            if not section:
                continue
            e = Entry(name, section, value, inline, " ".join(block), commented, line=i)
            e.modules = _modules(e, namelist)
            entries.append(e)
            continue
        if s.startswith("!"):
            if not _SEP.match(s):
                block.append(s.lstrip("! ").strip())
            continue
    return entries


def _looks_like_param(name: str, value: str) -> bool:
    """Un '!name = valor' comentado es un parámetro opcional (no una frase con '=' dentro de un comentario)."""
    v = value.strip()
    return bool(v) and " " not in v.split(",")[0].strip() and not re.search(r"[a-zA-Z]{4,}\s[a-zA-Z]{4,}", v)


def _modules(e: Entry, namelist: str) -> list[str]:
    if namelist in NAMELIST_MODULE:
        return [NAMELIST_MODULE[namelist]]
    if e.base in _IOF_MODULE:
        return [_IOF_MODULE[e.base]]
    text = f"{e.block} {e.inline}"
    mods = [k for k, hints in _MODULE_HINTS if any(h.lower() in text.lower() for h in hints)]
    if e.base in ("msc2", "mdc2", "icou_elfe_wwm", "nstep_wwm", "iwbl", "hmin_radstress", "drampwafo", "turbinj", "turbinjds", "alphaw", "fwvor_advxy_stokes",
                  "fwvor_advz_stokes", "fwvor_gradpress", "fwvor_breaking", "fwvor_streaming", "fwvor_wveg", "fwvor_wveg_NL", "cur_wwm", "wafo_obcramp"):
        mods = ["wwm"]
    if e.base in ("sed_class",):
        mods = ["sed"]
    if e.base in ("ntracer_gen",):
        mods = ["gen"]
    if e.base in ("ntracer_age",):
        mods = ["age"]
    if e.base in ("eco_class",):
        mods = ["eco"]
    if e.base in ("iharind",):
        mods = ["ha"]
    return mods


@lru_cache(maxsize=None)
def catalog(namelist: str = "param.nml") -> list[Entry]:
    return parse(template_path(namelist), namelist)


def sections(namelist: str = "param.nml") -> list[str]:
    out = []
    for e in catalog(namelist):
        if e.section not in out:
            out.append(e.section)
    return out


def defaults(namelist: str = "param.nml") -> dict[str, str]:
    return {e.name: e.default for e in catalog(namelist)}


@lru_cache(maxsize=None)
def auto_keys(namelist: str = "param.nml") -> frozenset[str]:
    """Claves que SCHISMlab fija automáticamente a partir del YAML (se leen del código de setup.py / waves.py)."""
    src_dir = Path(__file__).resolve().parent.parent
    if namelist == "param.nml":
        text = (src_dir / "setup.py").read_text(encoding="utf-8")
        keys = set(re.findall(r'self\.param\["(\w+(?:\(\d+\))?)"\]', text))
        for call in re.findall(r"self\.param\.update\((.*?)\)\n", text, re.S):
            keys.update(re.findall(r"\b(\w+)=", call))
            keys.update(re.findall(r'"(\w+\(\d+\))"', call))
        keys.update(re.findall(r'"(\w+)\(', text))          # f"iof_hydro({i})"
        keys.discard("flags"); keys.discard("self")
        return frozenset(keys)
    if namelist == "wwminput.nml":
        text = (src_dir / "forcing" / "waves.py").read_text(encoding="utf-8")
        return frozenset(re.findall(r'_set\(t, "(\w+)"', text))
    return frozenset()


def is_auto(e: Entry, namelist: str = "param.nml") -> bool:
    keys = auto_keys(namelist)
    return e.name in keys or e.base in keys


# ----------------------------------------------------------------------------- descripciones cortas (es, en)
DESC: dict[str, tuple[str, str]] = {
    # &CORE
    "ipre": ("Modo de preproceso: 1 comprueba la malla y para (usar 1 núcleo).", "Pre-processing mode: 1 checks the grid and stops (use 1 core)."),
    "ibc": ("0 baroclino (T y S activas en la dinámica), 1 barotrópico.", "0 baroclinic (T and S active in the dynamics), 1 barotropic."),
    "ibtp": ("Con ibc=1: 1 transporta T y S como trazadores pasivos, 0 no los calcula.", "With ibc=1: 1 transports T and S as passive tracers, 0 skips them."),
    "rnday": ("Duración total de la simulación en días.", "Total run length in days."),
    "dt": ("Paso de tiempo en segundos (SCHISM es implícito: puede ser grande, pero limita la precisión).", "Time step in seconds (SCHISM is implicit: can be large, but limits accuracy)."),
    "msc2": ("Número de frecuencias del espectro de oleaje (igual que MSC en wwminput.nml).", "Number of wave frequencies (same as MSC in wwminput.nml)."),
    "mdc2": ("Número de direcciones del espectro de oleaje (igual que MDC en wwminput.nml).", "Number of wave directions (same as MDC in wwminput.nml)."),
    "ntracer_gen": ("Número de trazadores genéricos (módulo GEN).", "Number of generic tracers (GEN module)."),
    "ntracer_age": ("Número de trazadores de edad, debe ser 2·N (módulo AGE).", "Number of age tracers, must be 2·N (AGE module)."),
    "sed_class": ("Clases de sedimento (módulo SED3D).", "Sediment classes (SED3D module)."),
    "eco_class": ("Variables del modelo EcoSim (25–60).", "EcoSim state variables (25–60)."),
    "nbins_veg_vert": ("Capas verticales de vegetación (si iveg≠0).", "Vertical vegetation bins (if iveg≠0)."),
    "nspool": ("Cada cuántos pasos se escriben las salidas.", "Output every this many time steps."),
    "ihfskip": ("Pasos por fichero de salida (cada ihfskip pasos empieza out2d_N.nc).", "Steps per output stack (a new out2d_N.nc every ihfskip steps)."),
    # &OPT: tiempo, coordenadas, física
    "ipre2": ("Segundo preproceso: escribe diagnósticos (p.ej. coeficientes de arrastre) y para.", "Second pre-processor: writes diagnostics (e.g. drag coefficients) and stops."),
    "itransport_only": ("1/2: resuelve sólo el transporte de trazadores con campos de velocidad guardados.", "1/2: solve only tracer transport using saved velocity fields."),
    "iloadtide": ("Marea de carga (self-attraction and loading) desde loadtide_*.gr3.", "Load tide (self-attraction and loading) from loadtide_*.gr3."),
    "loadtide_coef": ("Coeficiente de la marea de carga (0.1 típico).", "Load tide coefficient (0.1 typical)."),
    "start_year": ("Año de inicio (para sflux, mareas y fechas en las salidas).", "Start year (for sflux, tides and output dates)."),
    "start_month": ("Mes de inicio.", "Start month."), "start_day": ("Día de inicio.", "Start day."),
    "start_hour": ("Hora de inicio (decimal).", "Start hour (decimal)."),
    "utc_start": ("Huso horario del inicio (horas respecto a UTC).", "Time zone of the start (hours from UTC)."),
    "ics": ("Sistema de coordenadas de hgrid.gr3: 1 cartesiano (m), 2 lon/lat.", "Coordinate system of hgrid.gr3: 1 Cartesian (m), 2 lon/lat."),
    "rearth_pole": ("Radio polar de la Tierra (m).", "Polar radius of the Earth (m)."), "rearth_eq": ("Radio ecuatorial de la Tierra (m).", "Equatorial radius of the Earth (m)."),
    "ncor": ("Coriolis: 0 constante (coricoef), -1 latitud fija (rlatitude), 1 plano beta o latitud real según ics.", "Coriolis: 0 constant (coricoef), -1 fixed latitude (rlatitude), 1 beta plane or true latitude depending on ics."),
    "coricoef": ("Valor de f (s⁻¹) si ncor=0.", "Value of f (s⁻¹) if ncor=0."),
    "rlatitude": ("Latitud (°) para f si ncor=-1.", "Latitude (°) for f if ncor=-1."),
    "sfea0": ("Latitud de referencia (°) del plano beta si ncor=1 e ics=1.", "Reference latitude (°) of the beta plane if ncor=1 and ics=1."),
    "slam0": ("Longitud de referencia (°) si ncor=1 e ics=1.", "Reference longitude (°) if ncor=1 and ics=1."),
    "nchi": ("Fricción de fondo: 0 coeficiente de arrastre (drag.gr3), -1 Manning (manning.gr3), 1 rugosidad (rough.gr3).", "Bottom friction: 0 drag coefficient (drag.gr3), -1 Manning (manning.gr3), 1 roughness (rough.gr3)."),
    "dzb_min": ("Espesor mínimo de la capa de fondo (m) para la ley logarítmica (nchi=1).", "Minimum bottom layer thickness (m) for the log law (nchi=1)."),
    "hmin_man": ("Profundidad mínima (m) en la fórmula de Manning.", "Minimum depth (m) in the Manning formula."),
    "ihorcon": ("Viscosidad horizontal: 0 ninguna, 1 laplaciana, 2 bilaplaciana.", "Horizontal viscosity: 0 none, 1 Laplacian, 2 bi-Laplacian."),
    "hvis_coef0": ("Coeficiente de viscosidad horizontal (adimensional, ≤0.125 si ihorcon=2).", "Horizontal viscosity coefficient (dimensionless, ≤0.125 if ihorcon=2)."),
    "ishapiro": ("Filtro de Shapiro sobre la velocidad: 0 no, 1 constante (shapiro0), 2 por nodo (shapiro.gr3), -1 Smagorinsky.", "Shapiro filter on velocity: 0 off, 1 constant (shapiro0), 2 per node (shapiro.gr3), -1 Smagorinsky."),
    "shapiro0": ("Intensidad del filtro de Shapiro (0–0.5; 0.5 máxima).", "Shapiro filter strength (0–0.5; 0.5 strongest)."),
    "niter_shap": ("Iteraciones del filtro de Shapiro por paso.", "Shapiro filter iterations per step."),
    "thetai": ("Factor de implicitud (0.5 Crank–Nicolson, 1 totalmente implícito; 0.6 típico).", "Implicitness factor (0.5 Crank–Nicolson, 1 fully implicit; 0.6 typical)."),
    "nrampbc": ("Rampa de los gradientes baroclinos (1) durante drampbc días.", "Ramp baroclinic pressure gradients (1) over drampbc days."),
    "drampbc": ("Duración de la rampa baroclina (días).", "Baroclinic ramp duration (days)."),
    "ihot": ("Arranque: 0 desde cero, 1 desde hotstart.nc (tiempo 0), 2 continuar desde hotstart.nc.", "Start: 0 cold, 1 from hotstart.nc (time 0), 2 continue from hotstart.nc."),
    "ieos_type": ("Ecuación de estado: 0 UNESCO, 1 lineal.", "Equation of state: 0 UNESCO, 1 linear."),
    "ieos_pres": ("Incluir la presión en la ecuación de estado (sólo ieos_type=0).", "Include pressure in the equation of state (ieos_type=0 only)."),
    "eos_a": ("Coef. de dilatación térmica (lineal) kg/m³/°C.", "Thermal expansion coef. (linear EOS) kg/m³/°C."),
    "eos_b": ("Coef. salino (lineal) kg/m³/psu.", "Haline coef. (linear EOS) kg/m³/psu."),
    "slr_rate": ("Subida del nivel del mar (mm/día) aplicada en los contornos.", "Sea-level rise rate (mm/day) applied at the boundaries."),
    "nstep_wwm": ("Cada cuántos pasos de SCHISM se llama a WWM.", "Call WWM every this many SCHISM steps."),
    "icou_elfe_wwm": ("Acoplamiento con WWM: 0 sin acoplar, 1 completo (corrientes y nivel a WWM, fuerza de olas a SCHISM), otros parciales.", "WWM coupling: 0 none, 1 full (currents and levels to WWM, wave force to SCHISM), others partial."),
    "iwbl": ("Capa límite de olas en el fondo: 0 no, 1 Grant–Madsen, 2 Soulsby.", "Wave bottom boundary layer: 0 off, 1 Grant–Madsen, 2 Soulsby."),
    "hmin_radstress": ("Profundidad mínima (m) para calcular el tensor de radiación.", "Minimum depth (m) for the radiation stress."),
    "drampwafo": ("Rampa de las fuerzas de oleaje (días).", "Wave force ramp (days)."),
    "turbinj": ("Fracción de energía disipada por rotura inyectada como turbulencia (TKE).", "Fraction of breaking dissipation injected as turbulence (TKE)."),
    "turbinjds": ("Fracción de la disipación por whitecapping inyectada como TKE.", "Fraction of whitecapping dissipation injected as TKE."),
    "alphaw": ("Fracción de la disipación de olas en el fondo que va a TKE.", "Fraction of wave bottom dissipation that goes to TKE."),
    "fwvor_advxy_stokes": ("Vórtice: advección horizontal por la deriva de Stokes.", "Vortex force: horizontal Stokes drift advection."),
    "fwvor_advz_stokes": ("Vórtice: advección vertical por Stokes.", "Vortex force: vertical Stokes advection."),
    "fwvor_gradpress": ("Vórtice: gradiente de presión inducido por olas.", "Vortex force: wave-induced pressure gradient."),
    "fwvor_breaking": ("Vórtice: aceleración por rotura.", "Vortex force: breaking acceleration."),
    "fwvor_streaming": ("Vórtice: streaming en la capa límite.", "Vortex force: bottom streaming."),
    "fwvor_wveg": ("Vórtice: disipación por vegetación.", "Vortex force: vegetation dissipation."),
    "cur_wwm": ("Corriente que ve WWM: 0 superficial, 1 promediada en vertical, 2 ponderada con kh.", "Current seen by WWM: 0 surface, 1 depth-averaged, 2 kh-weighted."),
    "wafo_obcramp": ("Rampa de la fuerza de olas junto a los contornos abiertos.", "Wave force ramp near open boundaries."),
    "imm": ("Fondo móvil: 0 fijo, 1 prescrito, 2 por el módulo de sedimentos.", "Moving bed: 0 fixed, 1 prescribed, 2 by the sediment module."),
    "ibdef": ("Pasos de deformación del fondo si imm=1.", "Bed deformation steps if imm=1."),
    "ihydraulics": ("Estructuras hidráulicas (hydraulics.in).", "Hydraulic structures (hydraulics.in)."),
    "if_source": ("Fuentes y sumideros de volumen y trazadores: 0 no, 1 source_sink.in + vsource.th, -1 source.nc.", "Volume and tracer sources/sinks: 0 off, 1 source_sink.in + vsource.th, -1 source.nc."),
    "dramp_ss": ("Rampa de las fuentes (días).", "Source ramp (days)."),
    "meth_sink": ("Tratamiento de sumideros cuando el nodo se seca.", "Sink treatment when the node dries."),
    "lev_tr_source": ("Nivel vertical donde se inyecta cada trazador (-9 toda la columna).", "Vertical level where each tracer is injected (-9 whole column)."),
    "ihdif": ("Difusividad horizontal de trazadores (hdif.gr3).", "Horizontal tracer diffusivity (hdif.gr3)."),
    "nws": ("Atmósfera: 0 nada, 1 wind.th uniforme, 2 sflux (ERA5), -1 atmos.nc, 4 campos propios.", "Atmosphere: 0 none, 1 uniform wind.th, 2 sflux (ERA5), -1 atmos.nc, 4 own fields."),
    "wtiminc": ("Intervalo (s) de los datos de viento (wind.th) o de sflux.", "Time interval (s) of wind.th or sflux data."),
    "nrampwind": ("Rampa del viento (1) durante drampwind días.", "Wind ramp (1) over drampwind days."),
    "drampwind": ("Duración de la rampa de viento (días).", "Wind ramp duration (days)."),
    "iwindoff": ("Multiplicar el viento por windfactor.gr3.", "Scale the wind with windfactor.gr3."),
    "iwind_form": ("Fórmula del arrastre del viento: -1 Pond & Pickard, 1 Hwang (2018), -2 Zeng (bulk).", "Wind drag formula: -1 Pond & Pickard, 1 Hwang (2018), -2 Zeng (bulk)."),
    "model_type_pahm": ("Modelo paramétrico de huracán (USE_PAHM).", "Parametric hurricane model (USE_PAHM)."),
    "ihconsv": ("Flujos de calor en superficie (1) a partir de sflux_rad y sflux_air.", "Surface heat fluxes (1) from sflux_rad and sflux_air."),
    "isconsv": ("Flujo de agua dulce (evaporación − precipitación) en la salinidad (necesita PREC_EVAP).", "Freshwater flux (evaporation − precipitation) on salinity (needs PREC_EVAP)."),
    "i_hmin_airsea_ex": ("Cómo limitar el intercambio aire-mar en aguas someras.", "How to limit air–sea exchange in shallow water."),
    "hmin_airsea_ex": ("Profundidad mínima (m) para el intercambio aire-mar.", "Minimum depth (m) for air–sea exchange."),
    "i_hmin_salt_ex": ("Cómo limitar el flujo de agua dulce en aguas someras.", "How to limit the freshwater flux in shallow water."),
    "hmin_salt_ex": ("Profundidad mínima (m) para el flujo de agua dulce.", "Minimum depth (m) for the freshwater flux."),
    "iprecip_off_bnd": ("Anular la precipitación junto a contornos abiertos.", "Switch off precipitation near open boundaries."),
    "itur": ("Cierre turbulento: 0 constante, -1 perfil, 2 Pacanowski–Philander, 3 GLS (k-kl, k-ε, k-ω), 5 GOTM.", "Turbulence closure: 0 constant, -1 profile, 2 Pacanowski–Philander, 3 GLS (k-kl, k-ε, k-ω), 5 GOTM."),
    "dfv0": ("Viscosidad vertical constante (itur=0).", "Constant vertical viscosity (itur=0)."), "dfh0": ("Difusividad vertical constante (itur=0).", "Constant vertical diffusivity (itur=0)."),
    "mid": ("Esquema GLS: KL, KE, KW, UB (umlauf-burchard).", "GLS scheme: KL, KE, KW, UB (Umlauf–Burchard)."),
    "stab": ("Funciones de estabilidad GLS: GA (Galperin) o KC (Kantha–Clayson).", "GLS stability functions: GA (Galperin) or KC (Kantha–Clayson)."),
    "xlsc0": ("Escala de longitud de mezcla en superficie y fondo (m) para GLS.", "Surface/bottom mixing length scale (m) for GLS."),
    "inu_elev": ("Relajación (nudging) de la elevación hacia un valor con elev_nudge.gr3.", "Nudge the elevation with elev_nudge.gr3."),
    "inu_uv": ("Relajación de la velocidad hacia cero (esponja) con uv_nudge.gr3.", "Nudge velocity to zero (sponge) with uv_nudge.gr3."),
    "inu_tr": ("Relajación de cada trazador: 0 no, 1 a la condición inicial, 2 a *_nu.nc.", "Nudge each tracer: 0 off, 1 to the initial condition, 2 to *_nu.nc."),
    "nu_sum_mult": ("Cómo combinar nudging horizontal y vertical (1 suma, 2 producto).", "How to combine horizontal and vertical nudging (1 sum, 2 product)."),
    "vnh1": ("Profundidad (m) donde empieza el nudging vertical.", "Depth (m) where vertical nudging starts."), "vnf1": ("Factor de nudging vertical en vnh1.", "Vertical nudging factor at vnh1."),
    "vnh2": ("Profundidad (m) del segundo tramo de nudging vertical.", "Depth (m) of the second vertical nudging segment."), "vnf2": ("Factor de nudging vertical en vnh2.", "Vertical nudging factor at vnh2."),
    "step_nu_tr": ("Intervalo (s) de los campos *_nu.nc.", "Interval (s) of the *_nu.nc fields."),
    "h1_bcc": ("Profundidad (m) a partir de la cual se suaviza el gradiente baroclino.", "Depth (m) from which the baroclinic gradient is smoothed."),
    "h2_bcc": ("Profundidad (m) donde el suavizado baroclino es total.", "Depth (m) where the baroclinic smoothing is complete."),
    "hw_depth": ("Profundidad (m) para suavizar el gradiente baroclino en el fondo.", "Depth (m) to smooth the near-bottom baroclinic gradient."),
    "hw_ratio": ("Relación de alturas para el suavizado del fondo.", "Height ratio for the near-bottom smoothing."),
    "ihhat": ("Volumen conservado de forma estricta (1) usando ĥ.", "Strict volume conservation (1) using ĥ."),
    "inunfl": ("Inundación (1) con malla fina en zonas intermareales.", "Inundation (1) on fine meshes for intertidal zones."),
    "h0": ("Profundidad mínima (m) para que un nodo esté mojado.", "Minimum depth (m) for a node to be wet."),
    "shorewafo": ("Fuerza de olas sólo en nodos mojados junto a la orilla.", "Wave force only at wet nodes near the shore."),
    "moitn0": ("Iteraciones mínimas del solver de la elevación.", "Minimum iterations of the elevation solver."), "mxitn0": ("Iteraciones máximas del solver de la elevación.", "Maximum iterations of the elevation solver."),
    "rtol0": ("Tolerancia relativa del solver de la elevación.", "Relative tolerance of the elevation solver."),
    "nadv": ("Advección de momento: 0 por nodo (adv.gr3), 1 Euler, 2 Runge–Kutta 2.", "Momentum advection: 0 per node (adv.gr3), 1 Euler, 2 2nd-order Runge–Kutta."),
    "dtb_max": ("Paso máximo (s) del backtracking.", "Maximum backtracking sub-step (s)."), "dtb_min": ("Paso mínimo (s) del backtracking.", "Minimum backtracking sub-step (s)."),
    "inter_mom": ("Interpolación de la velocidad en el backtracking: 0 lineal, 1 cuadrática Kriging, -1 por nodo (krvel.gr3).", "Velocity interpolation in backtracking: 0 linear, 1 Kriging quadratic, -1 per node (krvel.gr3)."),
    "kr_co": ("Función de covarianza del Kriging.", "Kriging covariance function."),
    "itr_met": ("Método de transporte de trazadores: 1 upwind, 2 TVD explícito, 3 TVD implícito, 4 TVD².", "Tracer transport method: 1 upwind, 2 explicit TVD, 3 implicit TVD, 4 TVD²."),
    "h_tvd": ("Profundidad (m) por encima de la cual se usa upwind en vez de TVD.", "Depth (m) above which upwind replaces TVD."),
    "eps1_tvd_imp": ("Tolerancia del TVD implícito.", "Implicit TVD tolerance."), "eps2_tvd_imp": ("Segunda tolerancia del TVD implícito.", "Second implicit TVD tolerance."),
    "ielm_transport": ("Transporte ELM para trazadores en aguas someras (1).", "ELM transport for tracers in shallow water (1)."),
    "max_subcyc": ("Subciclos máximos del transporte explícito.", "Maximum sub-cycles of explicit transport."),
    "ip_weight": ("Pesos de la interpolación del transporte.", "Transport interpolation weights."),
    "inu_tr": ("Nudging de trazadores: 0 no, 1 a la condición inicial, 2 a *_nu.nc.", "Tracer nudging: 0 off, 1 to the initial condition, 2 to *_nu.nc."),
    "iupwind_mom": ("Upwind en la advección de momento (1).", "Upwind momentum advection (1)."),
    "indvel": ("Velocidad en los nodos: 0 por integral de Kriging (más suave), 1 promedio de elementos.", "Velocity at nodes: 0 Kriging integral (smoother), 1 element average."),
    "ihorcon": ("Viscosidad horizontal: 0 ninguna, 1 laplaciana, 2 bilaplaciana.", "Horizontal viscosity: 0 none, 1 Laplacian, 2 bi-Laplacian."),
    "ielad_weno": ("Esquema WENO para ELAD.", "WENO scheme for ELAD."),
    "iflux": ("Escribir flujos a través de secciones (fluxflag.prop).", "Write fluxes through sections (fluxflag.prop)."),
    "izonal5": ("Prueba de Williamson 5 (flujo zonal sobre una montaña).", "Williamson test 5 (zonal flow over a mountain)."),
    "ibtrack_test": ("Test del backtracking (flujo de rotación sólida).", "Backtracking test (solid-body rotation)."),
    "irouse_test": ("Test del perfil de Rouse.", "Rouse profile test."),
    "flag_fib": ("Opciones del módulo FIB (bacterias).", "FIB module (bacteria) options."),
    "slam0": ("Longitud de referencia (°) para proyectar si ics=1 con ncor=1.", "Reference longitude (°) for projection if ics=1 with ncor=1."),
    "ielm_transport": ("ELM para trazadores en zonas someras (1).", "ELM for tracers in shallow regions (1)."),
    "iunder_deep": ("Mezcla reducida bajo la profundidad h_bcc1.", "Reduced mixing below depth h_bcc1."),
    "h_bcc1": ("Profundidad (m) desde la cual se reduce la mezcla.", "Depth (m) from which mixing is reduced."),
    "vclose_surf_frac": ("Fracción de la capa superficial donde se cierra la velocidad.", "Fraction of the surface layer where velocity closure applies."),
    "iadjust_mass_consv0": ("Corrección de conservación de masa por trazador.", "Mass conservation correction per tracer."),
    "ipre_veg": ("Vegetación: preproceso.", "Vegetation: pre-processing."), "iveg": ("Vegetación: 0 no, 1 con veg_*.gr3.", "Vegetation: 0 off, 1 with veg_*.gr3."),
    "veg_vert_z": ("Cotas verticales de la vegetación.", "Vegetation vertical levels."), "veg_vert_scale_cd": ("Escalado vertical del arrastre vegetal.", "Vertical scaling of vegetation drag."),
    "veg_vert_scale_N": ("Escalado vertical de la densidad vegetal.", "Vertical scaling of vegetation density."), "veg_vert_scale_D": ("Escalado vertical del diámetro vegetal.", "Vertical scaling of vegetation diameter."),
    "veg_lai": ("Índice de área foliar (entero).", "Leaf area index (integer)."), "veg_cw": ("Coeficiente de la vegetación (entero).", "Vegetation coefficient (integer)."),
    "iharind": ("Análisis armónico en línea (harm.in, USE_HA).", "On-line harmonic analysis (harm.in, USE_HA)."),
    "iout_sta": ("Series temporales en estaciones (station.in) → staout_*.", "Time series at stations (station.in) → staout_*."),
    "nspool_sta": ("Cada cuántos pasos se escriben las estaciones.", "Write stations every this many steps."),
    "nhot": ("Escribir hotstart (1) cada nhot_write pasos.", "Write hotstart (1) every nhot_write steps."),
    "nhot_write": ("Pasos entre hotstarts (múltiplo de ihfskip y de nspool_sta).", "Steps between hotstarts (multiple of ihfskip and nspool_sta)."),
    "iof_hydro": ("Variables hidrodinámicas de salida (1 activa). Índices: 1 elev, 2 presión atm, 3 T aire, ... 26 velocidad horizontal 3D.", "Hydrodynamic output variables (1 on). Indices: 1 elev, 2 air pressure, 3 air T, ... 26 3D horizontal velocity."),
    "iof_wwm": ("Variables de oleaje de salida (1 Hs, 2 Tm01, 3 Tm02, 4 TM10, 5 k medio, 6 L media, 7 dirección media, 8 dispersión, 9 Tp, 16 dirección dominante, 19 velocidad orbital...).", "Wave output variables (1 Hs, 2 Tm01, 3 Tm02, 4 TM10, 5 mean k, 6 mean L, 7 mean direction, 8 spreading, 9 Tp, 16 dominant direction, 19 orbital velocity...)."),
    "iof_sed": ("Variables de sedimentos de salida.", "Sediment output variables."), "iof_ice": ("Variables de hielo de salida.", "Ice output variables."),
    "iof_gen": ("Trazadores genéricos de salida.", "Generic tracer outputs."), "iof_age": ("Edad del agua de salida.", "Water age outputs."),
    "iof_eco": ("Variables EcoSim de salida.", "EcoSim outputs."), "iof_icm": ("Variables ICM de salida.", "ICM outputs."), "iof_cos": ("Variables CoSiNE de salida.", "CoSiNE outputs."),
    "iof_fib": ("Variables FIB de salida.", "FIB outputs."), "iof_ana": ("Salidas de análisis (balances).", "Analysis outputs (balances)."), "iof_marsh": ("Salidas de marismas.", "Marsh outputs."),
    "iof_dvd": ("Salidas DVD (análisis de difusión).", "DVD outputs (diffusion analysis)."),
    "iof_ugrid": ("Salida en formato UGRID (1).", "UGRID output format (1)."),
    "nc_out": ("Escribir salidas netCDF (1).", "Write netCDF outputs (1)."),
    "iof_icm_core": ("Salidas del núcleo ICM.", "ICM core outputs."),
    "inv_atm_bnd": ("Barómetro inverso en los contornos abiertos (1): suma −(p−p₀)/(ρg) a la elevación impuesta.", "Inverse barometer at open boundaries (1): adds −(p−p₀)/(ρg) to the imposed elevation."),
    "prmsl_ref": ("Presión de referencia (Pa) del barómetro inverso.", "Reference pressure (Pa) for the inverse barometer."),
    "flag_ic": ("Condición inicial por trazador: 1 desde *_ic.gr3 (T,S: temp.ic/salt.ic), 2 desde ts.ic 1D, 0 hotstart.", "Initial condition per tracer: 1 from *_ic.gr3 (T,S: temp.ic/salt.ic), 2 from 1D ts.ic, 0 hotstart."),
    "gen_wsett": ("Velocidad de sedimentación (m/s) de los trazadores GEN.", "Settling velocity (m/s) of GEN tracers."),
    "ibcc_mean": ("Restar la densidad media (1) en el gradiente baroclino.", "Subtract the mean density (1) in the baroclinic gradient."),
    "rmaxvel": ("Velocidad máxima permitida (m/s), mayor se recorta.", "Maximum allowed velocity (m/s), larger values are clipped."),
    "velmin_btrack": ("Velocidad mínima (m/s) en el backtracking.", "Minimum velocity (m/s) in backtracking."),
    "btrack_nudge": ("Desplazamiento inicial del backtracking (fracción).", "Initial backtracking nudge (fraction)."),
    "ibtrack_openbnd": ("Permitir backtracking a través de contornos abiertos.", "Allow backtracking through open boundaries."),
    "iwater_type": ("Tipo de agua de Jerlov (1–7) para la penetración de la radiación solar.", "Jerlov water type (1–7) for solar radiation penetration."),
    "albedo": ("Albedo de la superficie del mar.", "Sea-surface albedo."),
    "level_age": ("Niveles donde se inyectan los trazadores de edad.", "Levels where age tracers are injected."),
    "iof_ugrid": ("Salida UGRID.", "UGRID output."),
    "ic_elev": ("Elevación inicial: 0 cero, 1 desde elev.ic.", "Initial elevation: 0 zero, 1 from elev.ic."),
    "nramp_elev": ("Rampa de la elevación impuesta en contornos (1).", "Ramp the imposed boundary elevation (1)."),
    "nramp_ss": ("Rampa de las fuentes.", "Source ramp."),
    "ishapiro_violation": ("Aviso al violar el criterio del filtro.", "Warn when the filter criterion is violated."),
    "iwbl": ("Capa límite de olas: 0 no, 1 Grant–Madsen, 2 Soulsby.", "Wave boundary layer: 0 off, 1 Grant–Madsen, 2 Soulsby."),
    "icou_elfe_wwm": ("Acoplamiento con WWM (0 ninguno, 1 completo).", "WWM coupling (0 none, 1 full)."),
    # wwminput.nml (PROC, COUPL, GRID, INIT, BOUC, ENGS, NUMS, HISTORY, STATION, HOTFILE)
    "PROCNAME": ("Nombre de la simulación.", "Simulation name."),
    "DIMMODE": ("Dimensiones: 2 (malla no estructurada).", "Dimensions: 2 (unstructured mesh)."),
    "LSTEA": ("Modo estacionario.", "Steady-state mode."), "LQSTEA": ("Modo cuasi-estacionario con subiteraciones.", "Quasi-steady mode with sub-iterations."),
    "LSPHE": ("Coordenadas esféricas (lon/lat).", "Spherical coordinates (lon/lat)."),
    "LNAUTIN": ("Convención náutica para las direcciones de entrada.", "Nautical convention for input directions."), "LNAUTOUT": ("Convención náutica en las salidas.", "Nautical convention for outputs."),
    "LMONO_IN": ("Oleaje monocromático en el contorno.", "Monochromatic boundary waves."), "LMONO_OUT": ("Salidas como altura monocromática.", "Outputs as monochromatic height."),
    "BEGTC": ("Inicio (yyyymmdd.hhmmss).", "Start (yyyymmdd.hhmmss)."), "DELTC": ("Paso de tiempo de WWM (s) = dt·nstep_wwm.", "WWM time step (s) = dt·nstep_wwm."),
    "UNITC": ("Unidad de DELTC.", "Unit of DELTC."), "ENDTC": ("Fin (yyyymmdd.hhmmss).", "End (yyyymmdd.hhmmss)."),
    "DMIN": ("Profundidad mínima (m) para WWM: debe ser < 1 m (la tabla de números de onda se tabula a 1 m).", "Minimum depth (m) for WWM: must be < 1 m (the wave-number table is built at 1 m)."),
    "LCPL": ("Acoplamiento con SCHISM.", "Coupling with SCHISM."), "RADFLAG": ("Formulación de la fuerza de olas: LON (Longuet-Higgins) o VOR (vórtice).", "Wave force formulation: LON (Longuet-Higgins) or VOR (vortex force)."),
    "LETOT": ("Fuerza de olas con el espectro total.", "Wave force from the total spectrum."), "NLVT": ("Niveles verticales (igual que SCHISM).", "Vertical levels (same as SCHISM)."),
    "DTCOUP": ("Intervalo de acoplamiento (s).", "Coupling interval (s)."), "IMET_DRY": ("Método para la fuerza de olas en zonas secas.", "Wave force method at dry areas."),
    "LCIRD": ("Direcciones circulares (0–360).", "Circular directions (0–360)."), "LSTAG": ("Direcciones desplazadas media celda.", "Staggered directions."),
    "MINDIR": ("Dirección mínima (°).", "Minimum direction (°)."), "MAXDIR": ("Dirección máxima (°).", "Maximum direction (°)."),
    "MDC": ("Número de direcciones.", "Number of directions."), "FRLOW": ("Frecuencia mínima (Hz).", "Lowest frequency (Hz)."), "FRHIGH": ("Frecuencia máxima (Hz).", "Highest frequency (Hz)."),
    "MSC": ("Número de frecuencias.", "Number of frequencies."), "FILEGRID": ("Malla para WWM (hgrid_WWM.gr3).", "WWM grid (hgrid_WWM.gr3)."),
    "IGRIDTYPE": ("Formato de la malla: 3 = gr3 de SCHISM.", "Grid format: 3 = SCHISM gr3."), "LSLOP": ("Limitar la pendiente del fondo.", "Limit bottom slope."), "SLMAX": ("Pendiente máxima.", "Maximum slope."),
    "LVAR1D": ("Espaciado variable en 1D.", "Variable spacing in 1D."), "LOPTSIG": ("Discretización óptima en frecuencia.", "Optimal frequency discretisation."),
    "LHOTR": ("Arrancar desde un hotfile de WWM.", "Start from a WWM hotfile."), "LINID": ("Condición inicial paramétrica a partir del viento (T) o espectro nulo (F).", "Parametric initial condition from the wind (T) or empty spectrum (F)."),
    "INITSTYLE": ("Estilo de la condición inicial: 1 paramétrica, 2 WW3.", "Initial condition style: 1 parametric, 2 WW3."),
    "LBCSE": ("Condición de contorno dependiente del tiempo.", "Time-dependent boundary condition."), "LBINTER": ("Interpolar en el tiempo el contorno.", "Interpolate the boundary in time."),
    "LBCWA": ("Espectro paramétrico en el contorno (WBHS, WBTP, WBDM...).", "Parametric boundary spectrum (WBHS, WBTP, WBDM...)."), "LBCSP": ("Espectro leído de fichero en el contorno.", "Boundary spectrum from file."),
    "LINHOM": ("Contorno no uniforme en el espacio.", "Spatially non-uniform boundary."), "LBSP1D": ("Formato 1D del fichero de espectro.", "1D spectrum file format."), "LBSP2D": ("Formato 2D del fichero de espectro.", "2D spectrum file format."),
    "FILEWAVE": ("Fichero de oleaje en el contorno.", "Boundary wave file."), "LBOUNDFORMAT": ("Formato del fichero de contorno.", "Boundary file format."), "IBOUNDFORMAT": ("1 WWM, 3 WW3 netCDF.", "1 WWM, 3 WW3 netCDF."),
    "WBHS": ("Hs (m) en el contorno.", "Hs (m) at the boundary."), "WBSS": ("Forma del espectro en el contorno (1 Pierson–Moskowitz, 2 JONSWAP, 3 bin...).", "Boundary spectral shape (1 Pierson–Moskowitz, 2 JONSWAP, 3 bin...)."),
    "WBTP": ("Periodo (s) en el contorno (pico o medio según WBSS).", "Period (s) at the boundary (peak or mean per WBSS)."), "WBDM": ("Dirección media (°) en el contorno.", "Mean direction (°) at the boundary."),
    "WBDSMS": ("Tipo de dispersión direccional (1 en grados, 2 exponente cos^m).", "Directional spreading type (1 degrees, 2 cos^m power)."), "WBDS": ("Dispersión direccional.", "Directional spreading."), "WBGAUSS": ("Anchura gaussiana del espectro.", "Gaussian spectral width."),
    "WBPKEN": ("Parámetro γ de JONSWAP.", "JONSWAP γ parameter."),
    "MESNL": ("Interacciones no lineales cuádruples (DIA): 1 sí.", "Quadruplet nonlinear interactions (DIA): 1 on."), "MESIN": ("Fuente de viento: 1 Ardhuin ST4, 2 Cycle 4 (Janssen), 3 Makin, 4 Donelan, 5 Cycle 3.", "Wind input: 1 Ardhuin ST4, 2 Cycle 4 (Janssen), 3 Makin, 4 Donelan, 5 Cycle 3."),
    "IFRIC": ("Capa límite atmosférica (1 para MESIN=1, 4 para MESIN=3).", "Atmospheric boundary layer (1 for MESIN=1, 4 for MESIN=3)."),
    "MESBF": ("Fricción de fondo: 1 JONSWAP, 2 Madsen, 3 SHOWEX; 0 ninguna.", "Bottom friction: 1 JONSWAP, 2 Madsen, 3 SHOWEX; 0 none."), "FRICC": ("Coeficiente de fricción de fondo (0.067 JONSWAP mar de viento, 0.038 mar de fondo).", "Bottom friction coefficient (0.067 JONSWAP wind sea, 0.038 swell)."),
    "MESBR": ("Rotura por fondo: 1 sí.", "Depth-induced breaking: 1 on."), "IBREAK": ("Modelo de rotura: 1 Battjes–Janssen, 2 Thornton–Guza, 3 Baldock...", "Breaking model: 1 Battjes–Janssen, 2 Thornton–Guza, 3 Baldock..."),
    "ICRIT": ("Criterio de rotura (1 γ constante, 2 pendiente...).", "Breaking criterion (1 constant γ, 2 slope...)."), "BRCR": ("Índice de rotura γ = H/d.", "Breaker index γ = H/d."),
    "a_BRCR": ("Coeficiente a del criterio de rotura variable.", "Coefficient a of the variable breaking criterion."), "b_BRCR": ("Coeficiente b.", "Coefficient b."), "min_BRCR": ("γ mínimo.", "Minimum γ."), "max_BRCR": ("γ máximo.", "Maximum γ."), "a_BIPH": ("Parámetro bifase.", "Biphase parameter."),
    "BR_COEF_METHOD": ("Método para el coeficiente de rotura.", "Breaking coefficient method."), "B_ALP": ("Coeficiente α de rotura.", "Breaking α coefficient."), "ZPROF_BREAK": ("Perfil vertical de la disipación por rotura.", "Vertical profile of breaking dissipation."),
    "BC_BREAK": ("Rotura en los nodos de contorno.", "Breaking at boundary nodes."), "IROLLER": ("Roller de superficie.", "Surface roller."), "ALPROL": ("Parámetro α del roller.", "Roller α parameter."),
    "MEVEG": ("Disipación por vegetación.", "Vegetation dissipation."), "LMAXETOT": ("Limitar Hs en aguas someras con el límite de Miche (rotura).", "Limit Hs in shallow water with the Miche breaking limiter."),
    "MESDS": ("Whitecapping (mismo valor que MESIN).", "Whitecapping (same value as MESIN)."), "MESTR": ("Interacciones triples: 0 no, 1 LTA, 2 LTA corregida.", "Triad interactions: 0 off, 1 LTA, 2 corrected LTA."),
    "TRICO": ("Coeficiente de las tríadas.", "Triad coefficient."), "TRIRA": ("Ratio de las tríadas.", "Triad ratio."), "TRIURS": ("Número de Ursell umbral para tríadas.", "Ursell number threshold for triads."),
    "ICOMP": ("Esquema numérico: 0 explícito, 1-3 implícito (3 = totalmente implícito, el único en paralelo sin PETSc).", "Numerical scheme: 0 explicit, 1-3 implicit (3 = fully implicit, the only parallel option without PETSc)."),
    "AMETHOD": ("Método de advección: 7 = Jacobi/Gauss-Seidel en bloque (paralelo sin PETSc).", "Advection method: 7 = block Jacobi/Gauss-Seidel (parallel without PETSc)."),
    "SMETHOD": ("Integración de los términos fuente: 1 Patankar implícito-explícito.", "Source-term integration: 1 implicit-explicit Patankar."), "DMETHOD": ("Integración en dirección: 2 CNTG.", "Directional integration: 2 CNTG."),
    "RTHETA": ("Factor de implicitud en dirección.", "Directional implicitness factor."), "LITERSPLIT": ("Dividir en sub-iteraciones.", "Split into sub-iterations."),
    "LFILTERTH": ("Filtro en dirección.", "Directional filter."), "MAXCFLTH": ("CFL máximo en dirección.", "Maximum directional CFL."), "FMETHOD": ("Integración en frecuencia: 1 CNTG.", "Frequency integration: 1 CNTG."),
    "LFILTERSIG": ("Filtro en frecuencia.", "Frequency filter."), "MAXCFLSIG": ("CFL máximo en frecuencia.", "Maximum frequency CFL."), "LLIMT": ("Limitador de acción (recomendado T).", "Action limiter (recommended T)."),
    "MELIM": ("Formulación del limitador.", "Limiter formulation."), "LIMFAK": ("Coeficiente del limitador.", "Limiter coefficient."), "LDIFR": ("Difracción (aprox. desacoplada en fase).", "Diffraction (phase-decoupled approx.)."),
    "IDIFFR": ("Formulación de la difracción.", "Diffraction formulation."), "LCONV": ("Escribir información de convergencia.", "Write convergence information."), "LCFL": ("Escribir números CFL.", "Write CFL numbers."),
    "NQSITER": ("Subiteraciones cuasi-estacionarias.", "Quasi-steady sub-iterations."), "QSCONV1": ("Convergencia 1 (fracción de nodos).", "Convergence 1 (fraction of nodes)."),
    "LEXPIMP": ("Implícito para frecuencias bajas.", "Implicit for low frequencies."), "FREQEXP": ("Frecuencia umbral para LEXPIMP.", "Threshold frequency for LEXPIMP."),
    "EPSH1": ("Tolerancia de convergencia relativa en Hs.", "Relative convergence tolerance on Hs."), "EPSH2": ("Tolerancia absoluta en Hs.", "Absolute tolerance on Hs."), "EPSH3": ("Tolerancia en periodo.", "Period tolerance."), "EPSH4": ("Tolerancia en dirección.", "Direction tolerance."),
    "LVECTOR": ("Rutinas vectorizadas (grandes clústeres).", "Vectorised routines (large clusters)."), "IVECTOR": ("Tipo de vectorización.", "Vectorisation type."),
    "LADVTEST": ("Test de advección.", "Advection test."), "LCHKCONV": ("Comprobar convergencia.", "Check convergence."), "DTMIN_DYN": ("Paso mínimo dinámico (s).", "Minimum dynamic step (s)."),
    "NDYNITER": ("Iteraciones dinámicas.", "Dynamic iterations."), "DTMIN_SIN": ("Paso mínimo para la fuente de viento.", "Minimum step for wind input."), "DTMIN_SNL4": ("Paso mínimo para SNL4.", "Minimum step for SNL4."),
    "DTMIN_SDS": ("Paso mínimo para whitecapping.", "Minimum step for whitecapping."), "DTMIN_SNL3": ("Paso mínimo para tríadas.", "Minimum step for triads."), "DTMIN_SBR": ("Paso mínimo para rotura.", "Minimum step for breaking."), "DTMIN_SBF": ("Paso mínimo para fricción.", "Minimum step for bottom friction."),
    "NDYNITER_SIN": ("Iteraciones para viento.", "Iterations for wind input."), "NDYNITER_SNL4": ("Iteraciones para SNL4.", "Iterations for SNL4."), "NDYNITER_SDS": ("Iteraciones para whitecapping.", "Iterations for whitecapping."), "NDYNITER_SBR": ("Iteraciones para rotura.", "Iterations for breaking."), "NDYNITER_SNL3": ("Iteraciones para tríadas.", "Iterations for triads."), "NDYNITER_SBF": ("Iteraciones para fricción.", "Iterations for bottom friction."),
    "LSOUBOUND": ("Términos fuente en los nodos de contorno.", "Source terms at boundary nodes."), "WAE_SOLVERTHR": ("Tolerancia del solver de la ecuación de acción.", "Action-equation solver tolerance."),
    "MAXITER": ("Iteraciones máximas del solver.", "Maximum solver iterations."), "PMIN": ("Porcentaje máximo de nodos sin converger.", "Maximum percentage of non-converged nodes."),
    "LNANINFCHK": ("Comprobar NaN/Inf (lento).", "Check for NaN/Inf (slow)."), "LZETA_SETUP": ("Calcular el wave setup (ecuación simple).", "Compute wave setup (simple equation)."), "ZETA_METH": ("Método del setup.", "Setup method."),
    "LSOURCESWAM": ("Física de aguas profundas de WAM (ECMWF).", "ECMWF WAM deep-water physics."), "BLOCK_GAUSS_SEIDEL": ("Gauss–Seidel en bloque (T) o Jacobi.", "Block Gauss–Seidel (T) or Jacobi."),
    "LNONL": ("Resolver el sistema no lineal con Patankar.", "Solve the nonlinear system with Patankar."), "ASPAR_LOCAL_LEVEL": ("Nivel de almacenamiento local de ASPAR.", "ASPAR local storage level."),
    "L_SOLVER_NORM": ("Normalizar el residuo del solver.", "Normalise the solver residual."), "LACCEL": ("Acelerar la convergencia.", "Accelerate convergence."),
    "FILEHOT_OUT": ("Hotfile de salida.", "Output hotfile."), "LHOTF": ("Escribir hotfiles.", "Write hotfiles."), "HOTSTYLE_OUT": ("Formato del hotfile de salida.", "Output hotfile format."), "MULTIPLEOUT": ("Un fichero por proceso (1) o uno global (0).", "One file per process (1) or a single global file (0)."),
    "FILEHOT_IN": ("Hotfile de entrada.", "Input hotfile."), "HOTSTYLE_IN": ("Formato del hotfile de entrada.", "Input hotfile format."), "IHOTPOS_IN": ("Posición temporal en el hotfile de entrada.", "Time position in the input hotfile."), "MULTIPLEIN": ("Hotfile por proceso (1) o global (0).", "Per-process (1) or global (0) hotfile."),
    "OUTSTYLE": ("Salidas propias de WWM: 'NO' (se usan las de SCHISM), 'NC', 'XFN'.", "WWM's own outputs: 'NO' (use SCHISM's), 'NC', 'XFN'."), "FILEOUT": ("Fichero de salida de WWM.", "WWM output file."),
    "LOUTITER": ("Escribir en cada iteración.", "Write every iteration."), "LLOUTS": ("Salidas en estaciones.", "Station outputs."), "ILOUTS": ("Número de estaciones.", "Number of stations."), "NLOUTS": ("Nombres de las estaciones.", "Station names."),
    "IOUTS": ("Número de estaciones de WWM.", "Number of WWM stations."), "NOUTS": ("Nombres de estaciones de WWM.", "WWM station names."), "XOUTS": ("Coordenadas x de las estaciones.", "Station x coordinates."), "YOUTS": ("Coordenadas y de las estaciones.", "Station y coordinates."),
    "CUTOFF": ("Frecuencia de corte para los parámetros integrales.", "Cut-off frequency for integral parameters."), "LSP1D": ("Espectros 1D en estaciones.", "1D spectra at stations."), "LSP2D": ("Espectros 2D en estaciones.", "2D spectra at stations."), "LSIGMAX": ("Limitar la frecuencia máxima en las salidas.", "Limit the maximum frequency in outputs."),
    "LMONO_OUT": ("Salidas monocromáticas.", "Monochromatic outputs."), "DEFINETC": ("Tiempo (s) de la definición de la salida.", "Output definition time (s)."),
    "WINDFAC": ("Factor del viento.", "Wind factor."), "PRINTCONV": ("Imprimir convergencia.", "Print convergence."),
    "ListBEGTC": ("Inicio de las salidas.", "Output start."), "ListDELTC": ("Intervalo de las salidas.", "Output interval."), "ListUNITC": ("Unidad del intervalo.", "Interval unit."), "ListENDTC": ("Fin de las salidas.", "Output end."),
    "ListIGRIDTYPE": ("Formato de malla del nesting.", "Nesting grid format."), "ListFILEGRID": ("Malla del nesting.", "Nesting grid."), "ListFILEBOUND": ("Contorno del nesting.", "Nesting boundary."), "ListPrefix": ("Prefijo de los ficheros de nesting.", "Nesting file prefix."),
    "L_NESTING": ("Activar nesting.", "Enable nesting."), "L_HOTFILE": ("Hotfile en nesting.", "Hotfile in nesting."), "L_BOUC_PARAM": ("Parámetros de contorno en nesting.", "Boundary parameters in nesting."), "L_BOUC_SPEC": ("Espectros de contorno en nesting.", "Boundary spectra in nesting."),
    "NB_GRID_NEST": ("Número de mallas anidadas.", "Number of nested grids."),
    "USE_PARMETIS": ("Partición con ParMETIS.", "ParMETIS partitioning."), "PETSC_LOAD_BALANCE": ("Balanceo de carga de PETSc.", "PETSc load balancing."), "KSPTYPE": ("Solver de Krylov de PETSc.", "PETSc Krylov solver."), "RTOL": ("Tolerancia relativa de PETSc.", "PETSc relative tolerance."), "ABSTOL": ("Tolerancia absoluta de PETSc.", "PETSc absolute tolerance."), "DTOL": ("Tolerancia de divergencia.", "Divergence tolerance."), "MAXITS": ("Iteraciones máximas de PETSc.", "PETSc maximum iterations."), "INITIALGUESSNONZERO": ("Usar la solución anterior como inicio.", "Use the previous solution as initial guess."), "GMRESPREALLOCATE": ("Preasignar memoria GMRES.", "Preallocate GMRES memory."), "PCTYPE": ("Precondicionador de PETSc.", "PETSc preconditioner."),
    "LSTEADY": ("Estacionario.", "Steady."), "LWINDFROMWWM": ("Viento leído por WWM (F: lo da SCHISM).", "Wind read by WWM (F: provided by SCHISM)."),
    "LSEWL": ("Nivel del mar desde SCHISM.", "Water level from SCHISM."), "LSECU": ("Corrientes desde SCHISM.", "Currents from SCHISM."),
}
