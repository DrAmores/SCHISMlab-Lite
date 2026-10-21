"""Construye el directorio de ejecucion completo de un caso (malla, vertical, CI, forzamientos, param.nml)."""
from __future__ import annotations
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
import numpy as np
from .case import Case
from .edition import pro
from .io.gr3 import Mesh, read_gr3, write_gr3, write_prop
from .io.param import write_param
from .mesh.build import build_mesh
from .mesh.idealized import R_EARTH
from .forcing import VGrid, write_sflux, write_wind_th, write_elev_ic, write_tracer_ic_gr3, write_bctides, write_hotstart
from .expressions import evaluate, uses, is_expression
from .initial import is_geographic, domain_frame, expression_vars

log = logging.getLogger(__name__)

OUTPUT_VARS = {  # nombre en el YAML -> (indice iof_hydro, 3D?, vector?)  — catálogo completo de param.nml v5.13
    "elevation": (1, False, False), "airPressure": (2, False, False), "airTemperature": (3, False, False),
    "specificHumidity": (4, False, False), "solarRadiation": (5, False, False), "sensibleHeat": (6, False, False),
    "latentHeat": (7, False, False), "upwardLongwave": (8, False, False), "downwardLongwave": (9, False, False),
    "totalHeat": (10, False, False), "evaporationRate": (11, False, False), "precipitationRate": (12, False, False),
    "bottomStress": (13, False, True), "windSpeed": (14, False, True), "windStress": (15, False, True),
    "depthAverageVel": (16, False, True), "verticalVelocity": (17, True, False), "temperature": (18, True, False),
    "salinity": (19, True, False), "waterDensity": (20, True, False), "diffusivity": (21, True, False),
    "viscosity": (22, True, False), "turbulentKineticEner": (23, True, False), "mixingLength": (24, True, False),
    "zCoordinates": (25, True, False), "horizontalVel": (26, True, True), "horizontalSideVel": (27, True, True),
    "verticalVelAtElement": (28, True, False), "temperatureAtElement": (29, True, False), "salinityAtElement": (30, True, False),
    "pressure_gradient": (31, False, True),
}
OUTPUT_GROUPS = {   # para la página de salidas: grupo -> variables
    "basic": ["elevation", "depthAverageVel", "bottomStress", "windSpeed", "windStress", "airPressure"],
    "atmos": ["airTemperature", "specificHumidity", "solarRadiation", "sensibleHeat", "latentHeat", "upwardLongwave",
              "downwardLongwave", "totalHeat", "evaporationRate", "precipitationRate"],
    "3d": ["horizontalVel", "verticalVelocity", "temperature", "salinity", "waterDensity", "zCoordinates",
           "diffusivity", "viscosity", "turbulentKineticEner", "mixingLength"],
    "advanced": ["horizontalSideVel", "verticalVelAtElement", "temperatureAtElement", "salinityAtElement", "pressure_gradient"],
}
STATION_VARS = ["elev", "airP", "windx", "windy", "T", "S", "u", "v", "w"]   # orden de las banderas de station.in


def tsunami_series(p: dict, rnday: float) -> list:
    """Onda de tsunami en el contorno como serie [[horas, m], ...] cada 30 s.

    shape: solitary (cresta sech², por defecto) | n_wave (seno de un periodo: cresta y valle) | leading_depression (valle y cresta)
    height (m), period_min (minutos), arrival_h (hora de llegada de la cresta, o del inicio en n_wave)
    waves: número de ondas del tren (1 por defecto); decay: factor de cada onda respecto a la anterior (1 = iguales)
    """
    H = float(p.get("height", 1.0)); T = float(p.get("period_min", 15.0)) * 60.0; t0 = float(p.get("arrival_h", 1.0)) * 3600.0
    shape = str(p.get("shape", "solitary")); nw = max(1, int(p.get("waves", 1))); dec = float(p.get("decay", 1.0))
    t = np.arange(0.0, rnday * 86400.0 + 60.0, 30.0)
    eta = np.zeros_like(t)
    for k in range(nw):                                         # tren: una onda por periodo
        Hk = H * dec ** k; tk = t0 + k * T
        if shape == "solitary":
            eta += Hk / np.cosh((t - tk) / (T / 4.0)) ** 2
        else:
            ph = np.clip((t - tk) / T, 0.0, 1.0)
            eta += Hk * np.sin(2 * np.pi * ph) * ((t >= tk) & (t <= tk + T)) * (-1 if shape == "leading_depression" else 1)
    return [[float(a / 3600.0), float(b)] for a, b in zip(t, eta)]


class RunSetup:
    def __init__(self, case: Case, outdir: Path | None = None):
        self.case = case
        self.cfg = case.cfg
        self.dir = Path(outdir or case.workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "outputs").mkdir(exist_ok=True)
        self.param: dict = {}
        self.nscribes = 1

    # ------------------------------------------------------------------ malla
    def mesh(self) -> Mesh:
        hg = self.dir / "hgrid.gr3"
        if hg.exists() and not (self.cfg.get("mesh") or {}).get("rebuild", False):
            log.info("usando la malla existente %s", hg)
            m = read_gr3(hg)
        else:
            m = build_mesh(self.case, self.dir)
        from .mesh.edits import sync_edits
        m = sync_edits(self.dir, (self.cfg.get("mesh") or {}) or {}, m)   # retoques de batimetria cambiados desde la malla
        slr = float((self.cfg.get("scenario") or {}).get("sea_level_rise", 0.0) or 0.0)
        applied = self.dir / "slr_applied"
        prev = float(applied.read_text()) if applied.exists() else 0.0
        if slr != prev:                                           # escenario: subir el nivel del mar = bajar la cota de todo el dominio
            m.depth = m.depth - prev + slr
            write_gr3(hg, m); applied.write_text(f"{slr}\n")
            log.info("subida del nivel del mar aplicada a la malla: %+.2f m", slr)
        self.m = m
        self.geographic = is_geographic(self.cfg)
        self.frame = domain_frame(m, self.cfg)                   # misma convención x, y, lon, lat que la interfaz
        self.xm, self.ym, self.lon, self.lat = self.frame["x"], self.frame["y"], self.frame["lon"], self.frame["lat"]
        if self.geographic:
            self.param.update(ics=2, ncor=1)                     # Coriolis completo: f = 2*omega*sin(lat) en cada nodo
        else:
            ref = self.cfg.get("reference", {"lon0": 0.0, "lat0": 45.0})
            lon0, lat0 = float(ref.get("lon0", 0.0)), float(ref.get("lat0", 45.0))
            cor = (self.cfg.get("physics") or {}).get("coriolis", "f-plane")
            if cor in ("none", False, 0):
                self.param.update(ics=1, ncor=0, coricoef=0.0)
            elif cor == "beta":
                self.param.update(ics=1, ncor=1, sfea0=lat0, slam0=lon0)   # beta-plane con hgrid.ll
            else:
                self.param.update(ics=1, ncor=-1, rlatitude=lat0)
        ll = Mesh(self.lon, self.lat, m.depth, m.elements, m.open_boundaries, m.land_boundaries, m.name)
        write_gr3(self.dir / "hgrid.ll", ll)
        return m

    def _vars(self, z=None, t=None):
        """Variables disponibles en las expresiones del YAML (en nodos)."""
        return expression_vars(self.frame, self.m.depth, z, t)

    # ------------------------------------------------------------------ vertical
    def vertical(self) -> VGrid:
        vc = (self.cfg.get("vertical") or {"type": "2d"})
        kind = vc.get("type", "2d")
        if kind == "2d":
            vg = VGrid.two_d()
        elif kind == "sigma":
            vg = VGrid.sigma(int(vc.get("nvrt", 20)), float(vc.get("h_c", 10)), float(vc.get("theta_b", 0)), float(vc.get("theta_f", 4)))
        elif kind == "sz":
            zl = sorted(float(z) for z in vc["zlevels"])
            hmax = float(self.m.depth.max())
            if zl[0] > -hmax:                      # SCHISM exige que el primer nivel z este por debajo de la maxima profundidad
                zl = [-(1.05 * hmax)] + zl
                log.info("nivel z inferior anadido en %.0f m (profundidad maxima %.0f m)", zl[0], hmax)
            vg = VGrid.sz(int(vc.get("nsigma", 20)), zl, float(vc.get("h_c", 10)), float(vc.get("theta_b", 0)), float(vc.get("theta_f", 4)))
        else:
            raise ValueError(f"vertical.type desconocido: {kind}")
        vg.write(self.dir / "vgrid.in")
        self.vg = vg
        return vg

    # ------------------------------------------------------------------ tiempo y fisica
    def time_and_physics(self):
        tc = (self.cfg.get("time") or {})
        start = tc.get("start", "2020-01-01")
        self.start = np.datetime64(str(start), "s")
        d = datetime.fromisoformat(str(self.start))
        self.rnday = float(tc.get("days", 1.0)); dt = float(tc.get("dt", 60.0))
        out_min = float((self.cfg.get("output") or {}).get("interval_minutes", 60.0))
        nspool = max(1, int(round(out_min * 60 / dt)))
        steps_per_day = int(round(86400 / dt))
        ihfskip = max(nspool, (steps_per_day // nspool) * nspool)     # un fichero de salida por dia
        self.param.update(start_year=d.year, start_month=d.month, start_day=d.day, start_hour=d.hour + d.minute / 60.0,
                          rnday=self.rnday, dt=dt, nspool=nspool, ihfskip=ihfskip, dramp=float(tc.get("ramp_days", 0.0)))
        ph = (self.cfg.get("physics") or {})
        baroclinic = bool(ph.get("baroclinic", False))
        if baroclinic and self.vg.nvrt == 2:
            log.warning("baroclinic: true con malla vertical 2D: se ejecuta barotropo (T y S no afectan al flujo)")
            baroclinic = False
        self.baroclinic = baroclinic
        self.param.update(ibc=0 if baroclinic else 1, ibtp=1 if (baroclinic or ph.get("transport", False)) else 0,
                          itur=0 if self.vg.nvrt == 2 else int(ph.get("turbulence", 3)),   # en 2D no hay cierre vertical (y evita leer diffmin/diffmax)
                          nchi=-1, hmin_man=float(ph.get("hmin_man", 0.2 if (self.cfg.get("mesh") or {}).get("inundation") else 1.0)), ihdif=0, ishapiro=int(ph.get("shapiro", 1)),
                          indvel=int(ph.get("indvel", 0)), ihorcon=int(ph.get("ihorcon", 0)),
                          hvis_coef0=float(ph.get("hvis_coef0", 0.025)), thetai=float(ph.get("thetai", 0.6)))
        fr = (self.cfg.get("friction") or {})
        if fr.get("landcover"):                                   # rugosidad por uso del suelo (WorldCover / CORINE / propio)
            from .edition import pro as _pro
            _pro_data_landcover = _pro("data.landcover")
            manning_from_landcover = _pro_data_landcover.manning_from_landcover
            size = float(((self.cfg.get("mesh") or {}).get("inundation") or {}).get("size", 100) or 100) if isinstance((self.cfg.get("mesh") or {}).get("inundation"), dict) else 100.0
            n, cls, src = manning_from_landcover(fr, self.lon, self.lat, self.m.depth, size_m=size)
            write_gr3(self.dir / "manning.gr3", self.m, values=n, boundaries=False, comment=f"Manning por uso del suelo ({src})")
            np.save(self.dir / "landcover_nodes.npy", cls); (self.dir / "landcover_source").write_text(src + "\n")
        else:
            write_gr3(self.dir / "manning.gr3", self.m, values=float(fr.get("manning", 0.025)), boundaries=False)
        inu = pro("mesh.inundation", "inundación / flooding").inundation_cfg(self.cfg.get("mesh") or {}) if (self.cfg.get("mesh") or {}).get("inundation") else None
        if inu:
            param_settings = pro("mesh.inundation").param_settings                                                   # secado y mojado para inundacion
            self.param.update(param_settings(inu))
            self.param.update({k: v for k, v in ph.items() if k in ("h0", "inunfl", "thetai", "ihhat")})
        # difusividad/viscosidad vertical minima y maxima: SCHISM las lee con itur = 3, 4 o 5; se escriben siempre (son baratas)
        write_gr3(self.dir / "diffmin.gr3", self.m, values=float(ph.get("diffmin", 1e-6)), boundaries=False)
        write_gr3(self.dir / "diffmax.gr3", self.m, values=float(ph.get("diffmax", 1.0)), boundaries=False)
        write_prop(self.dir / "tvd.prop", self.m, 1)

    # ------------------------------------------------------------------ condiciones iniciales
    def initial(self):
        ic = (self.cfg.get("initial") or {})
        eta = ic.get("elevation", 0.0)
        if is_expression(eta) or float(eta) != 0.0:
            write_elev_ic(self.dir / "elev.ic", self.m, evaluate(eta, **self._vars()))
            self.param["ic_elev"] = 1
        else:
            self.param["ic_elev"] = 0
        T, S = ic.get("temperature", 20.0), ic.get("salinity", 36.0)
        src = ic.get("source")
        if isinstance(src, str):
            src = {"name": src}
        if src and src.get("name", "").startswith(("medsea", "global", "cmems")):   # CI reales de Copernicus Marine
            from .edition import pro as _pro
            _pro_data_cmems = _pro("data.cmems")
            fetch_cmems = _pro_data_cmems.fetch_cmems
            initial_fields = _pro_data_cmems.initial_fields
            prod = src.get("name", "medsea").replace("cmems", "medsea")
            ds = fetch_cmems((float(self.lon.min()), float(self.lon.max())), (float(self.lat.min()), float(self.lat.max())),
                             str(self.start)[:10], str(self.start)[:10], product=prod)
            z = self.vg.zcor(self.m.depth)
            f = initial_fields(ds, self.lon, self.lat, z)
            eta = f.get("eta", np.zeros(self.m.nnodes))
            eta = eta - float(np.mean(eta))   # el nivel de Copernicus tiene un datum propio: se usa solo la anomalia espacial
            write_hotstart(self.dir / "hotstart.nc", self.m, self.vg, temp=f["temp"], salt=f["salt"], eta=eta)
            write_tracer_ic_gr3(self.dir / "temp.ic", self.m, f["temp"][:, -1]); write_tracer_ic_gr3(self.dir / "salt.ic", self.m, f["salt"][:, -1])
            self.param.update(ihot=1, **{"flag_ic(1)": 1, "flag_ic(2)": 1})
            return
        vel = ic.get("velocity") or {}
        u0, v0 = vel.get("u", 0.0), vel.get("v", 0.0)
        has_vel = is_expression(u0) or is_expression(v0) or float(u0) != 0.0 or float(v0) != 0.0
        tracers = self.baroclinic or bool(self.param.get("ibtp"))
        need_hot = has_vel or (tracers and (uses(T, "z") or uses(S, "z") or ic.get("hotstart", False)))
        eta_n = evaluate(eta, **self._vars()) * np.ones(self.m.nnodes)
        if need_hot:                                              # estado inicial 3D completo (eta, T, S, u, v)
            z = self.vg.zcor(self.m.depth, eta_n)
            v = self._vars(z=z)
            Tn, Sn = evaluate(T, **v) * np.ones_like(z), evaluate(S, **v) * np.ones_like(z)
            # u, v (este, norte; con ics=2 SCHISM los lee en el marco lon/lat) evaluados en el centro de cada lado
            from .forcing.hotstart import side_table
            sd = side_table(self.m)
            frame_s = {k: 0.5 * (a[sd[:, 0]] + a[sd[:, 1]]) for k, a in self.frame.items()}
            vs = expression_vars(frame_s, 0.5 * (self.m.depth[sd[:, 0]] + self.m.depth[sd[:, 1]]), 0.5 * (z[sd[:, 0]] + z[sd[:, 1]]))
            Us, Vs = (np.asarray(evaluate(e_, **vs), float) * np.ones((len(sd), z.shape[1])) for e_ in (u0, v0))
            write_hotstart(self.dir / "hotstart.nc", self.m, self.vg, temp=Tn, salt=Sn, eta=eta_n, u=Us, v=Vs)
            self.param.update(ihot=1)
            if has_vel:
                log.info("velocidad inicial (u, v) escrita en hotstart.nc")
        if tracers:
            if need_hot:
                write_tracer_ic_gr3(self.dir / "temp.ic", self.m, Tn[:, -1]); write_tracer_ic_gr3(self.dir / "salt.ic", self.m, Sn[:, -1])
            else:
                write_tracer_ic_gr3(self.dir / "temp.ic", self.m, evaluate(T, **self._vars()) * np.ones(self.m.nnodes))
                write_tracer_ic_gr3(self.dir / "salt.ic", self.m, evaluate(S, **self._vars()) * np.ones(self.m.nnodes))
                self.param["ihot"] = 0
            self.param.update(**{"flag_ic(1)": 1, "flag_ic(2)": 1})
        elif not need_hot:
            self.param["ihot"] = 0

    # ------------------------------------------------------------------ forzamientos
    def rivers(self):
        """Ríos (fuentes de volumen, T y S): forcing.rivers."""
        rivers = (self.cfg.get("forcing") or {}).get("rivers") or []
        if not rivers:
            self.param["if_source"] = 0
            return
        keys = pro("forcing.sources", "ríos / rivers").write_sources(self.dir, self.m, rivers, self.rnday, self.geographic)
        if rivers:
            log.info("%d rios como fuentes: %s", len(rivers), ", ".join(str(r.get("name", "?")) for r in rivers))
        self.param.update({k: v for k, v in keys.items() if k != "nramp_ss"})

    def forcing(self):
        fc = (self.cfg.get("forcing") or {})
        self.rivers()
        atm = fc.get("atmosphere")
        if atm and atm.get("source") == "era5":
            if fc.get("wind"):
                log.warning("forcing.wind se ignora: el viento viene de ERA5 (forcing.atmosphere)")
            self._era5(atm)
            return
        w = fc.get("wind")
        if not w:
            self.param["nws"] = 0
            return
        formula = int(w.get("formula", 1))
        st = w.get("stress")
        if st is not None:
            # esfuerzo (Pa) en vez de viento: se invierte la fórmula de arrastre de SCHISM para que windStress*1000 sea tau
            from .forcing.windstress import wind_from_stress, INVERTIBLE
            if not isinstance(st, dict):
                raise ValueError("forcing.wind.stress debe ser {x: tau_x, y: tau_y} en Pa (números o expresiones)")
            if formula not in INVERTIBLE:
                raise ValueError(f"forcing.wind.stress: la fórmula {formula} no se puede invertir; usa formula: 1 (Hwang) o -1 (Pond & Pichard)")
            cx, cy = st.get("x", 0.0), st.get("y", 0.0)
            def uv(**kw):
                return wind_from_stress(evaluate(cx, **kw), evaluate(cy, **kw), formula)
            log.info("viento dado como esfuerzo (Pa): tau_x=%s tau_y=%s; se convierte a viento a 10 m (formula %d)", cx, cy, formula)
        else:
            cx, cy = w.get("u", 0.0), w.get("v", 0.0)
            def uv(**kw):
                return evaluate(cx, **kw), evaluate(cy, **kw)
        ramp = float(w.get("ramp_days", 0.0))
        dt_h = float(w.get("dt_hours", 1.0))
        self.param.update(drampwind=ramp, iwind_form=formula, wtiminc=dt_h * 3600.0)
        write_gr3(self.dir / "windrot_geo2proj.gr3", self.m, values=0.0, boundaries=False)
        spatial = any(uses(e, n) for e in (cx, cy) for n in ("x", "y", "lon", "lat"))
        times = self.start + (np.arange(0, (self.rnday + 1) * 24 + dt_h, dt_h) * 3600.0).round().astype("timedelta64[s]")
        tdays = (times - self.start) / np.timedelta64(1, "D")
        if not spatial:
            uu, vv = uv(t=tdays)
            uu = uu * np.ones(tdays.size); vv = vv * np.ones(tdays.size)
            write_wind_th(self.dir / "wind.th", tdays * 86400.0, uu, vv)
            self.param["nws"] = 1
        else:
            pad = float(w.get("grid_pad_deg", 0.5)); ddeg = float(w.get("grid_dx_deg", 0.25))
            glon = np.arange(self.lon.min() - pad, self.lon.max() + pad + ddeg, ddeg)
            glat = np.arange(self.lat.min() - pad, self.lat.max() + pad + ddeg, ddeg)
            LON, LAT = np.meshgrid(glon, glat)
            lat0 = np.deg2rad(self.lat.mean())
            X = np.deg2rad(LON - self.lon.min()) * R_EARTH * np.cos(lat0); Y = np.deg2rad(LAT - self.lat.min()) * R_EARTH
            if not self.geographic:   # dominio cartesiano: x,y de la malla desde la esquina SW
                X, Y = X, Y
            UV = [uv(x=X, y=Y, lon=LON, lat=LAT, t=t) for t in tdays]
            U = np.stack([a * np.ones_like(LON) for a, _ in UV]); V = np.stack([b * np.ones_like(LON) for _, b in UV])
            write_sflux(self.dir / "sflux", glon, glat, times, {"uwind": U, "vwind": V}, self.start)
            self.param["nws"] = 2
        self.param.update(ihconsv=0, isconsv=0)

    def _era5(self, atm: dict):
        """Atmosfera real desde ERA5 (viento, presion, temperatura, humedad; opcional calor y lluvia). SCHISMlab Pro."""
        pro("setup_pro", "ERA5").era5(self, atm)

    # ------------------------------------------------------------------ contornos
    def boundaries(self):
        bc = (self.cfg.get("boundaries") or {})
        nope = len(self.m.open_boundaries)
        if isinstance(bc, list) and len(bc) != nope:
            raise ValueError(f"boundaries: la lista tiene {len(bc)} entradas y la malla {nope} contornos abiertos")
        entries = bc if isinstance(bc, list) else [bc] * nope
        tides, nodal, specs = [], {}, []
        src3d = bc.get("source") if isinstance(bc, dict) else None     # contornos variables desde Copernicus Marine
        # profundidad minima en los contornos abiertos (evita chorros espurios en contornos que cortan la plataforma)
        bmin = float(bc.get("min_depth", 10.0)) if isinstance(bc, dict) else 10.0
        if bmin > 0 and self.m.open_boundaries:
            idx = np.unique(np.concatenate(self.m.open_boundaries))
            if (self.m.depth[idx] < bmin).any():
                log.info("profundidad minima %g m impuesta en %d nodos de contorno abierto", bmin, int((self.m.depth[idx] < bmin).sum()))
                self.m.depth[idx] = np.maximum(self.m.depth[idx], bmin)
                write_gr3(self.dir / "hgrid.gr3", self.m)
                if self.geographic:
                    ll = read_gr3(self.dir / "hgrid.ll"); ll.depth = self.m.depth; write_gr3(self.dir / "hgrid.ll", ll)
        tf = self.dir / "open_boundary_types.json"           # tipo de cada contorno abierto (lados del dominio): forced | radiation
        kinds = json.loads(tf.read_text()) if tf.exists() else []
        if len(kinds) != nope:
            kinds = ["forced"] * nope
        self._ob_forced = [k for k, kd in enumerate(kinds) if kd != "radiation"]
        if src3d:
            self._cmems_boundaries(src3d)
        th1 = []                                             # series de nivel de los contornos de tipo 1 (una columna cada uno)
        for kb, (b, nodes) in enumerate(zip(entries, self.m.open_boundaries)):
            if kinds[kb] == "radiation":                     # radiacion (Flather): deja salir las ondas, sin forzar
                specs.append(dict(elev="none", vel="flather", nvrt=self.vg.nvrt,
                                  temp="ic" if self.baroclinic else "none", salt="ic" if self.baroclinic else "none"))
                continue
            e = b.get("elevation", "none"); v = b.get("velocity", "none")
            T = b.get("temperature", "ic" if self.baroclinic else "none"); S = b.get("salinity", "ic" if self.baroclinic else "none")
            if src3d:
                v = "th"; T = "th" if self.baroclinic else "none"; S = "th" if self.baroclinic else "none"
                if (src3d.get("name") or "") == "schismlab":
                    if isinstance(e, dict) and "tides" in e:
                        log.warning("anidamiento: el nivel de la madre ya incluye la marea; se ignoran las mareas del contorno del hijo")
                    e = "th"                                                 # solo el nivel de la madre (incluye marea y presion)
                elif not (isinstance(e, dict) and "tides" in e):
                    e = "th"
            if isinstance(e, dict) and "tsunami" in e:         # onda de tsunami parametrizada -> serie de nivel
                e = {"series": tsunami_series(e["tsunami"], self.rnday)}
            if isinstance(e, dict) and "series" in e:          # serie de nivel (marejada, ola de tormenta): elev.th, tipo 1
                th1.append(e["series"]); e = "th1"
            if isinstance(e, dict) and "tides" in e:
                tc = e["tides"]; cons = [c.upper() for c in tc.get("constituents", ["M2"])]
                tides = tides + [c for c in cons if c not in tides]          # unión de constituyentes de todos los contornos
                src = tc.get("source", "idealized")
                if src != "idealized":                        # mareas reales de un modelo global
                    from .edition import pro as _pro
                    _pro_data_tides = _pro("data.tides")
                    tidal_constants = _pro_data_tides.tidal_constants
                    k = tidal_constants(self.lon[nodes], self.lat[nodes], cons, self.start, model=src)
                    nodal.update({c: dict(omega=k[c]["omega"], ff=k[c]["ff"], face=k[c]["face"]) for c in cons})
                    e = {"tides": {c: (k[c]["amp"], k[c]["phase_deg"]) for c in cons}}
                else:
                    amp, pha = tc.get("amplitude", 0.5), tc.get("phase", 0.0)
                    e = {"tides": {c: (amp if np.isscalar(amp) else amp[i], pha if np.isscalar(pha) else pha[i]) for i, c in enumerate(cons)}}
                if src3d:
                    e["th"] = True                                   # tipo 5: marea + elev2D.th.nc
            specs.append(dict(elev=e, vel=v, temp=T, salt=S))
        if th1:
            self._elev_th(th1)
        tp = bc.get("tidal_potential", False) if isinstance(bc, dict) else False
        write_bctides(self.dir / "bctides.in", self.m, specs, constituents=tides, tidal_potential=bool(tp), nodal=nodal)
        # capa esponja junto a los contornos abiertos (por defecto solo con mareas reales): amortigua chorros espurios
        sp = bc.get("sponge", "auto") if isinstance(bc, dict) else "auto"
        if sp == "auto":
            sp = {"width_km": 40, "relax_uv": 0.01, "relax_elev": 0.0} if nodal else None
        if sp and self.m.open_boundaries:
            self._sponge(float(sp.get("width_km", 40)), float(sp.get("relax_uv", 0.01)), float(sp.get("relax_elev", 0.0)))

    def _elev_th(self, series_list, step_s: float | None = None):
        """elev.th (tipo 1): una columna por contorno de tipo 1 (SCHISM lee nettype valores por línea), interpolada cada
        `step_s` desde [[horas, m], ...]."""
        dt = float(self.param.get("dt", 60.0))
        if step_s is None:                                       # tan fino como la serie dada (ondas de tsunami), maximo 5 min
            dts = min(float(np.diff(np.asarray(sr, float)[:, 0]).min()) * 3600.0 for sr in series_list if len(sr) > 1)
            step_s = min(300.0, max(dt, dts))
        step_s = max(dt, round(step_s / dt) * dt)                # múltiplo del paso de tiempo
        t = np.arange(0.0, self.rnday * 86400.0 + 2 * step_s, step_s)
        cols = [np.interp(t / 3600.0, np.asarray(sr, float)[:, 0], np.asarray(sr, float)[:, 1]) for sr in series_list]
        np.savetxt(self.dir / "elev.th", np.column_stack([t, *cols]), fmt="%.1f" + " %.4f" * len(cols))
        log.info("contorno: serie de nivel %.2f–%.2f m en elev.th para %d contornos (cada %.0f s)",
                 min(c.min() for c in cols), max(c.max() for c in cols), len(cols), step_s)

    def _cmems_boundaries(self, src: dict):
        """Contornos 3D variables desde Copernicus Marine o desde otra simulacion (anidamiento). SCHISMlab Pro."""
        pro("setup_pro", "contornos 3D / 3D boundaries").cmems_boundaries(self, src)

    def _sponge(self, width_km: float, relax_uv: float, relax_elev: float):
        """uv_nudge.gr3 / elev_nudge.gr3: relajacion (1/s) maxima en el contorno, decayendo linealmente a 0 en width_km."""
        from scipy.spatial import cKDTree
        ob = np.unique(np.concatenate(self.m.open_boundaries))
        xy = np.column_stack([self.xm, self.ym])
        d = cKDTree(xy[ob]).query(xy, k=1)[0] / 1e3
        w = np.clip(1 - d / width_km, 0, 1)
        dt = float(self.param.get("dt", 60.0))
        if relax_uv > 0:
            write_gr3(self.dir / "uv_nudge.gr3", self.m, values=np.minimum(relax_uv, 1 / dt) * w, boundaries=False)
            self.param["inu_uv"] = 1
        if relax_elev > 0:
            write_gr3(self.dir / "elev_nudge.gr3", self.m, values=np.minimum(relax_elev, 1 / dt) * w, boundaries=False)
            self.param["inu_elev"] = 1
        log.info("esponja de %g km junto a los contornos abiertos (relax uv %g 1/s)", width_km, relax_uv)

    # ------------------------------------------------------------------ salidas y param.nml
    def outputs(self):
        oc = (self.cfg.get("output") or {})
        want = list(oc.get("variables", ["elevation", "depthAverageVel"] + (["horizontalVel"] if self.vg.nvrt > 2 else [])))
        if ((self.cfg.get("forcing") or {}).get("wind") or {}).get("stress") is not None and "windStress" not in want:
            want.append("windStress")   # viento dado como esfuerzo: se guarda windStress para poder comprobar tau = windStress*1000
            log.info("se añade la salida windStress (viento dado como esfuerzo)")
        flags = {f"iof_hydro({i})": 0 for i, _, _ in OUTPUT_VARS.values()}
        n = 0
        for name in want:
            if name not in OUTPUT_VARS:
                raise ValueError(f"variable de salida desconocida: {name} (opciones: {list(OUTPUT_VARS)})")
            i, is3d, vec = OUTPUT_VARS[name]
            if is3d and self.vg.nvrt == 2:
                log.warning("variable de salida 3D '%s' ignorada: la malla vertical es 2D", name)
                continue
            flags[f"iof_hydro({i})"] = 1
            if is3d:
                n += 2 if vec else 1                              # un scribe por cada variable 3D (vector: una por componente)
        self.nscribes = max(1, n + 1 + getattr(self, "_extra_scribes", 0))   # +1: el scribe de out2d (todas las 2D)
        self.param.update(flags)
        # estaciones: series temporales en puntos fijos (outputs/staout_*)
        # pilas de ficheros (ihfskip): por defecto un fichero por día; `output.stack_hours` lo cambia.
        # SCHISM exige: ihfskip múltiplo de nspool; nhot_write múltiplo de ihfskip y de nspool_sta -> ihfskip múltiplo de mcm(nspool, nspool_sta)
        import math
        dt = float(self.param["dt"]); nspool = int(self.param["nspool"])
        stations = self.cfg.get("stations") or []
        nsta = max(1, int(round(float(oc.get("station_interval_minutes", 10)) * 60 / dt))) if stations else 1
        unit = math.lcm(nspool, nsta)
        stack_h = oc.get("stack_hours")
        if stack_h and not self.param.get("_single_stack"):
            self.param["ihfskip"] = max(unit, int(round(float(stack_h) * 3600 / dt)) // unit * unit)
        elif int(self.param["ihfskip"]) % unit:
            self.param["ihfskip"] = max(unit, int(self.param["ihfskip"]) // unit * unit)
        ihf = int(self.param["ihfskip"])
        hot_h = float(oc.get("hotstart_hours", 0) or 0)
        if hot_h > 0:
            self.param.update(nhot=1, nhot_write=max(ihf, int(round(hot_h * 3600 / dt)) // ihf * ihf))
        else:
            self.param["nhot"] = 0
        if stations:
            sv = oc.get("station_variables", ["elev", "T", "S", "u", "v", "w"])
            flags = " ".join("1" if k in sv else "0" for k in STATION_VARS)
            lines = [f"{flags} !elev, airP, windx, windy, T, S, u, v, w", f"{len(stations)}"]
            for i, s_ in enumerate(stations, 1):
                if "lon" in s_:
                    if not self.geographic:
                        raise ValueError("estaciones en lon/lat en un dominio cartesiano: usa x, y")
                    x, y = float(s_["lon"]), float(s_["lat"])
                else:
                    x, y = float(s_["x"]), float(s_["y"])
                    if self.geographic:                       # x, y en metros desde la esquina SO -> lon/lat (SCHISM los exige con ics=2)
                        lat0 = np.deg2rad(float(self.lat.mean()))
                        x = float(self.m.x.min()) + np.rad2deg(x / (R_EARTH * np.cos(lat0))); y = float(self.m.y.min()) + np.rad2deg(y / R_EARTH)
                        log.info("estación %s dada en metros: convertida a lon/lat (%.4f, %.4f)", s_.get("name", i), x, y)
                lines.append(f"{i} {x} {y} 0.0 !{s_.get('name', i)}")
            (self.dir / "station.in").write_text("\n".join(lines) + "\n")
            nhw = int(self.param.get("nhot_write", ihf * max(1, int(round(86400 / dt)) // ihf)))
            self.param.update(iout_sta=1, nspool_sta=nsta, nhot_write=max(ihf, nhw // ihf * ihf))
        self.param.update(self._nml_overrides("param.nml"))   # sobreescrituras directas del usuario (param: y namelists:)
        self.param.pop("_single_stack", None)
        write_param(self.dir / "param.nml", self.param)
        (self.dir / "nscribes").write_text(f"{self.nscribes}\n")

    def _nml_overrides(self, name: str) -> dict:
        """Sobreescrituras del YAML para un fichero .nml: `namelists: {param.nml: {...}, wwminput.nml: {...}}` (y `param:` para param.nml)."""
        nl = (self.cfg.get("namelists") or {}).get(name) or {}
        if name == "param.nml":
            nl = {**(self.cfg.get("param") or {}), **nl}
        return dict(nl)

    def extra_namelists(self):
        """Ficheros .nml de los demas modulos compilados (sediment.nml, ice.nml, ...): plantilla oficial + sobreescrituras del YAML."""
        from .build import required_namelists
        from .io.namelist_catalog import template_path
        for name in required_namelists(self.modules):
            if name == "wwminput.nml":
                continue
            write_param(self.dir / name, self._nml_overrides(name), template=template_path(name))
            log.info("%s escrito (modulo adicional)", name)

    def waves(self):
        """Oleaje (WWM): `waves: {enabled: true, nstep: 3, msc: 24, mdc: 24, boundary_hs: null, variables: [...]}`."""
        wc = self.cfg.get("waves") or {}
        from .build import effective_build
        self.variant, self.modules, built = effective_build(self.cfg)   # coherente con oleaje, precipitacion y `build`
        if not built:
            log.warning("la compilacion pschism_%s (modulos %s) no esta compilada: compilala en Instalacion antes de ejecutar", self.variant, ", ".join(self.modules))
        log.info("compilacion: pschism_%s (%s)", self.variant, ", ".join(self.modules))
        if not wc.get("enabled") and "wwm" not in self.modules:
            return
        pro("setup_pro", "oleaje WWM / WWM waves").waves(self, wc)

    def build(self):
        from .checks import require_lite_compatible
        require_lite_compatible(self.cfg)                      # SCHISMlab Lite: casos sin funciones de Pro
        self._extra_scribes = 0
        self.mesh(); self.vertical(); self.time_and_physics(); self.initial(); self.forcing(); self.boundaries(); self.waves(); self.outputs()
        self.extra_namelists()
        (self.dir / "variant").write_text(self.variant + "\n")
        (self.dir / "modules").write_text(" ".join(self.modules) + "\n")   # para compilar la misma variante en el cluster
        import yaml
        (self.dir / "caso.yaml").write_text(yaml.safe_dump(self.cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")   # instantánea: reproducibilidad
        log.info("caso '%s' preparado en %s (nscribes=%d)", self.case.name, self.dir, self.nscribes)
        return self.dir


def setup_case(case: Case, outdir: Path | None = None) -> Path:
    return RunSetup(case, outdir).build()


def setup_case_from_yaml(case_path: str) -> None:
    """Punto de entrada del proceso de preparacion de la interfaz (se puede detener): prepara los ficheros del caso."""
    setup_case(Case(case_path))
