/* Holographic anatomical twin (BodyParts3D meshes, CC BY 4.0) rendered with a custom fresnel/scan-line shader.
   Every alert colour comes from backend region states (ares/anatomy/mapping.py); nothing here decides severity. */
import { Bvh, CameraControls, Html, useGLTF } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { Suspense, useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import { STATE_LABEL, type RegionState } from "../api";

export type LayerKey = "skin" | "organs" | "vessels" | "skeleton" | "muscles";
export type ViewKey = "front" | "back" | "left" | "right" | "reset" | "focus";
export const MODES: Record<string, { label: string; layers: Record<LayerKey, boolean>; heartInVascular?: boolean }> = {
  hologram: { label: "Full hologram", layers: { skin: true, organs: true, vessels: true, skeleton: true, muscles: false } },
  transparent: { label: "Transparent body", layers: { skin: true, organs: false, vessels: false, skeleton: false, muscles: false } },
  organs: { label: "Internal organs", layers: { skin: true, organs: true, vessels: false, skeleton: false, muscles: false } },
  vascular: { label: "Blood vessels", layers: { skin: true, organs: false, vessels: true, skeleton: false, muscles: false }, heartInVascular: true },
  skeletal: { label: "Skeleton", layers: { skin: true, organs: false, vessels: false, skeleton: true, muscles: false } },
  muscles: { label: "Muscles", layers: { skin: false, organs: false, vessels: false, skeleton: true, muscles: true } },
};
const GLB = "/anatomy-assets/ares_body.glb";
const DEFAULT_VIEW = { key: "reset" as const, nonce: 0 };
const SEV = { observation: "#f2c94c", elevated: "#ff8a3d", critical: "#ff4d5e" } as Record<string, string>;
const ARTERIAL = new Set(["aorta", "arteries"]);
const VENOUS = new Set(["vena_cava", "veins"]);

const VERT = /* glsl */`
varying vec3 vN; varying vec3 vV; varying vec3 vW;
void main(){
  vec4 wp = modelMatrix * vec4(position, 1.0); vW = wp.xyz;
  vec4 mv = viewMatrix * wp; vV = -mv.xyz; vN = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * mv;
}`;
const FRAG = /* glsl */`
uniform vec3 uColor; uniform float uBase; uniform float uRim; uniform float uScan; uniform float uPulse;
uniform float uOpacity; uniform float uTime; uniform float uSweep;
varying vec3 vN; varying vec3 vV; varying vec3 vW;
void main(){
  float f = 1.0 - abs(dot(normalize(vN), normalize(vV)));
  f = pow(f, 2.0);
  float scan = 0.5 + 0.5 * sin(vW.y * 220.0 - uTime * 2.5);
  float sweep = exp(-pow((vW.y - uSweep) * 28.0, 2.0));
  float a = (uBase + f * uRim + scan * uScan + sweep * 0.18) * uOpacity * (1.0 + 0.9 * uPulse);
  vec3 c = uColor * (0.45 + 1.5 * f + 0.9 * sweep) + uColor * uPulse * 0.8;
  gl_FragColor = vec4(c, clamp(a, 0.0, 1.0));
}`;

export interface RegionMeta { id: string; label: string; layer: LayerKey | "vessels"; system: string; center: [number, number, number]; size: [number, number, number]; triangles: number }
interface Props {
  meta: RegionMeta[]; states: Record<string, any>; frameStates?: Record<string, RegionState> | null;
  layers: Record<LayerKey, boolean>; heartInVascular?: boolean; skinOpacity?: number;
  selected?: string | null; selectedIds?: string[] | null; hovered?: string | null; isolate?: boolean;
  onHover?: (id: string | null) => void; onSelect?: (id: string | null) => void;
  view?: { key: ViewKey; region?: string; nonce: number }; compact?: boolean; glow?: boolean; showEvidence?: boolean;
  radiation?: { intensity: number; spe: boolean } | null; labels?: boolean;
}

function regionOf(m: THREE.Object3D) { return (m.name || m.parent?.name || "").replace(/_\d+$/, ""); }

function Body(p: Props) {
  const { scene } = useGLTF(GLB);
  const metaById = useMemo(() => Object.fromEntries(p.meta.map((m) => [m.id, m])), [p.meta]);
  const meshes = useMemo(() => {
    const out: Record<string, THREE.Mesh> = {};
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const id = regionOf(m);
      m.material = new THREE.ShaderMaterial({
        vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        uniforms: { uColor: { value: new THREE.Color("#3fd8ff") }, uBase: { value: 0.05 }, uRim: { value: 0.6 }, uScan: { value: 0.02 },
          uPulse: { value: 0 }, uOpacity: { value: 1 }, uTime: { value: 0 }, uSweep: { value: 1 } },
      });
      m.userData.regionId = id;
      m.userData.raycast0 = m.raycast;
      m.renderOrder = id === "skin" ? 10 : 1;
      if (!m.geometry.attributes.normal) m.geometry.computeVertexNormals();
      out[id] = m;
    });
    return out;
  }, [scene]);
  const group = useRef<THREE.Group>(null);
  const clock = useRef(0);
  useFrame((_, dt) => {
    clock.current += dt;
    const t = clock.current;
    const sweep = 0.05 + ((t * 0.32) % 1) * 1.85;
    const pulse = 0.5 + 0.5 * Math.sin(t * 4.2);
    if (p.compact && group.current) group.current.rotation.y += dt * 0.25;
    const L = p.layers;
    for (const [id, m] of Object.entries(meshes)) {
      const u = (m.material as THREE.ShaderMaterial).uniforms;
      u.uTime.value = t; u.uSweep.value = sweep;
      const meta = metaById[id];
      const layer = (meta?.layer ?? "organs") as LayerKey;
      const st: string | undefined = p.frameStates?.[id] ?? p.states[id]?.state;
      let visible = id === "skin" ? L.skin : L[layer];
      if (!visible && id === "heart" && p.heartInVascular && L.vessels) visible = true;
      if (!visible && id === "skin" && p.radiation && p.radiation.intensity > 0.05) visible = true;
      m.visible = Boolean(visible);
      let color = "#3fd8ff", base = 0.05, rim = 0.6, scan = 0.012, pul = 0, op = 1;
      if (id === "skin") {
        color = "#38c4ff"; base = 0.014; rim = 0.5; scan = 0.022; op = p.skinOpacity ?? 1;
        if (!L.skin) op = 0.35;
        if (p.radiation && p.radiation.intensity > 0.05) { color = "#9b7bff"; rim = 0.5 + 0.6 * Math.min(1, p.radiation.intensity); pul = p.radiation.spe ? 0.35 * pulse : 0; }
      } else if (layer === "skeleton") { color = "#cfe6ff"; base = 0.03; rim = 0.42; }
      else if (layer === "muscles") { color = "#3a96ff"; base = 0.03; rim = 0.42; }
      else if (layer === "vessels") {
        color = ARTERIAL.has(id) ? "#ff7c7c" : VENOUS.has(id) ? "#5b8cff" : "#3fd8ff"; base = 0.09; rim = 0.75;
      } else {   // organs
        const measured = st && st !== "not_monitored" && st !== "unknown";
        color = measured ? "#4fe6ff" : "#2c78c8"; base = measured ? 0.11 : 0.045; rim = measured ? 0.9 : 0.45;
        if (st === "unknown") { color = "#8a99b0"; base = 0.07; }
      }
      if (st && SEV[st]) {
        color = SEV[st]; base = st === "critical" ? 0.42 : 0.3; rim = 1.25;
        if (st === "critical") pul = pulse;
      }
      if (p.showEvidence && p.states[id]?.research_evidence?.length) { color = "#b38cff"; base = 0.16; rim = 1.0; pul = 0.25 * pulse; }
      const inSel = id === p.selected || !!p.selectedIds?.includes(id);
      if (id === p.hovered || inSel) { base += 0.1; rim += 0.4; }
      if (inSel && p.selected) { base += 0.06; rim += 0.25; }
      if (p.isolate && p.selected && !inSel && id !== "skin") op *= 0.12;
      u.uColor.value.set(color); u.uBase.value = base; u.uRim.value = rim; u.uScan.value = scan; u.uPulse.value = pul; u.uOpacity.value = op;
      // picking: only visible, non-skin structures (skin only when it is the sole layer)
      const internal = L.organs || L.vessels || L.skeleton || L.muscles;
      m.raycast = !m.visible || (id === "skin" && internal) || p.compact ? () => null : m.userData.raycast0;
    }
  });
  const over = (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); document.body.style.cursor = "pointer"; p.onHover?.(e.object.userData.regionId ?? null); };
  const click = (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); p.onSelect?.(e.object.userData.regionId ?? null); };
  return (
    <group ref={group}>
      <primitive object={scene} onPointerOver={over} onPointerOut={() => { document.body.style.cursor = ""; p.onHover?.(null); }} onClick={click} />
      {p.labels !== false && <Labels {...p} metaById={metaById} />}
    </group>
  );
}

function labelPos(m: RegionMeta): [number, number, number] {
  const [x, y, z] = m.center;
  if (Math.abs(x) > 0.03) return [x + Math.sign(x) * m.size[0] * 0.6, y + m.size[1] * 0.12, z];
  return [x, y + m.size[1] * 0.5, z + m.size[2] * 0.5];
}
function Labels(p: Props & { metaById: Record<string, RegionMeta> }) {
  const shown = Object.values(p.metaById).filter((m) => {
    if (m.id === "skin") return false;
    const st = p.frameStates?.[m.id] ?? p.states[m.id]?.state;
    return m.id === p.hovered || m.id === p.selected || (st && SEV[st]);
  });
  return <>{shown.map((m) => {
    const st = (p.frameStates?.[m.id] ?? p.states[m.id]?.state) as string | undefined;
    const alert = st && SEV[st];
    return (
      <Html key={m.id} position={labelPos(m)} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
        <div className={`tag3d ${alert ? st : ""}`}><b>{m.label}</b>{alert && st ? <span> · {STATE_LABEL[st]}</span> : null}</div>
      </Html>
    );
  })}</>;
}

function Platform() {
  const ring = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => { if (ring.current) ring.current.rotation.z += dt * 0.3; });
  const mat = (c: string, o: number) => new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
  return (
    <group rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.002, 0]}>
      <mesh material={mat("#3fd8ff", 0.55)}><ringGeometry args={[0.44, 0.452, 96]} /></mesh>
      <mesh material={mat("#3b82ff", 0.25)}><ringGeometry args={[0.5, 0.506, 96]} /></mesh>
      <mesh ref={ring} material={mat("#3fd8ff", 0.5)}><ringGeometry args={[0.52, 0.545, 64, 1, 0, Math.PI * 0.55]} /></mesh>
      <mesh material={mat("#1c64c8", 0.10)}><circleGeometry args={[0.44, 64]} /></mesh>
    </group>
  );
}

function CameraRig({ view, metaById, controls, compact }: { view?: Props["view"]; metaById: Record<string, RegionMeta>; controls: MutableRefObject<CameraControls | null>; compact?: boolean }) {
  useEffect(() => {
    const c = controls.current;
    if (!c || !view) return;
    const d = compact ? 2.9 : 3.1;
    if (view.key === "focus" && view.region && metaById[view.region]) {
      const m = metaById[view.region];
      const dist = Math.max(0.95, Math.max(...m.size) * 3.4);
      c.setLookAt(m.center[0] + dist * 0.22, m.center[1] + dist * 0.08, m.center[2] + dist, m.center[0], m.center[1], m.center[2], true);
      return;
    }
    const pos: Record<string, [number, number, number]> = { front: [0, 1.0, d], back: [0, 1.0, -d], left: [d, 1.0, 0], right: [-d, 1.0, 0], reset: [0, 1.05, d] };
    const pp = pos[view.key] ?? pos.reset;
    c.setLookAt(pp[0], pp[1], pp[2], 0, 0.92, 0, true);
  }, [view, metaById, controls, compact]);
  return null;
}

function StaticCamera() {        // compact (non-interactive) view: frame the whole body once
  const { camera } = useThree();
  useEffect(() => { camera.position.set(0, 1.0, 3.25); camera.lookAt(0, 0.9, 0); camera.updateProjectionMatrix(); }, [camera]);
  return null;
}

export default function Hologram(p: Props) {
  const controls = useRef<CameraControls | null>(null);
  const metaById = useMemo(() => Object.fromEntries(p.meta.map((m) => [m.id, m])), [p.meta]);
  return (
    <Canvas camera={{ position: [0, 1.05, p.compact ? 2.9 : 3.1], fov: 36, near: 0.05, far: 50 }} dpr={[1, 1.75]}
      onPointerMissed={() => p.onSelect?.(null)} gl={{ antialias: true, alpha: false }}>
      <color attach="background" args={["#030812"]} />
      <gridHelper args={[6, 30, "#0f3a66", "#0a2346"]} position={[0, 0, 0]} />
      <Platform />
      <Suspense fallback={<Html center><div className="loading">Loading anatomy (BodyParts3D)…</div></Html>}>
        <Bvh firstHitOnly><Body {...p} /></Bvh>
      </Suspense>
      {p.compact ? <StaticCamera /> : <>
        <CameraControls ref={controls} minDistance={0.3} maxDistance={7} smoothTime={0.5} />
        <CameraRig view={p.view ?? DEFAULT_VIEW} metaById={metaById} controls={controls} compact={p.compact} /></>}
      {p.glow !== false && <EffectComposer multisampling={0}><Bloom intensity={0.7} luminanceThreshold={0.12} luminanceSmoothing={0.3} mipmapBlur /></EffectComposer>}
    </Canvas>
  );
}

useGLTF.preload(GLB);
