/* Interactive 3D anatomical digital twin (BodyParts3D meshes, CC BY 4.0).
   Every colour change comes from backend region states; nothing here decides severity. */
import { Bvh, CameraControls, Html, useGLTF } from "@react-three/drei";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { Suspense, useEffect, useMemo, useRef, type MutableRefObject } from "react";
import * as THREE from "three";
import { STATE_COLOR, STATE_LABEL, type RegionInfo, type RegionMeta, type RegionState } from "../api";

export type LayerKey = "skin" | "muscles" | "skeleton" | "organs" | "risk" | "radiation";
export type ViewKey = "front" | "back" | "left" | "right";

const BASE_COLOR: Record<string, string> = {
  skin: "#b9a596", heart: "#a8423c", lung_left: "#c78f8c", lung_right: "#c78f8c", trachea: "#d6c0ad",
  brain: "#d4b2a6", liver: "#7c3b2f", kidney_left: "#8c4a3b", kidney_right: "#8c4a3b", stomach: "#c27e69",
  esophagus: "#b9806c", intestine_small: "#c99079", intestine_large: "#b7826a", spleen: "#6f3141",
  bladder: "#c8a25c", aorta: "#a83232", vena_cava: "#3d5fa3",
};
const LAYER_COLOR: Record<string, string> = { skeleton: "#ddd6c6", muscles: "#9c4f49" };
const GLB = "/anatomy-assets/ares_body.glb";

interface Props {
  regionsMeta: RegionMeta[];
  states: Record<string, RegionInfo>;          // live (or timeline frame) states from the mapping engine
  frameStates?: Record<string, RegionState> | null;
  layers: Record<LayerKey, boolean>;
  skinOpacity: number;
  selected: string | null;
  isolate: boolean;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  view: { key: ViewKey | "focus" | "reset"; region?: string; nonce: number };
  radiation: { intensity: number; spe: boolean } | null;
  showEvidence: boolean;
}

function layerOf(meta: RegionMeta | undefined): LayerKey {
  if (!meta) return "organs";
  return meta.layer === "vessels" ? "organs" : (meta.layer as LayerKey);
}

function Body({ regionsMeta, states, frameStates, layers, skinOpacity, selected, isolate, hovered, onHover, onSelect,
  radiation, showEvidence }: Omit<Props, "view">) {
  const { scene } = useGLTF(GLB);
  const metaById = useMemo(() => Object.fromEntries(regionsMeta.map((m) => [m.id, m])), [regionsMeta]);
  // one material per region, created once
  const meshes = useMemo(() => {
    const out: Record<string, THREE.Mesh> = {};
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const id = (m.name || m.parent?.name || "").replace(/_\d+$/, "");
      const meta = metaById[id];
      const base = BASE_COLOR[id] ?? LAYER_COLOR[meta?.layer ?? ""] ?? "#999";
      m.material = new THREE.MeshStandardMaterial({
        color: base, roughness: id === "skin" ? 0.75 : 0.55, metalness: 0.0, transparent: true,
        side: id === "skin" ? THREE.FrontSide : THREE.DoubleSide,
      });
      m.userData.regionId = id;
      m.userData.base = new THREE.Color(base);
      m.geometry.computeVertexNormals();
      out[id] = m;
    });
    return out;
  }, [scene, metaById]);

  const pulse = useRef(0);
  useFrame((_, dt) => {
    pulse.current += dt;
    const p = 0.55 + 0.45 * Math.sin(pulse.current * 4.2);
    for (const [id, m] of Object.entries(meshes)) {
      const mat = m.material as THREE.MeshStandardMaterial;
      const meta = metaById[id];
      const layer = layerOf(meta);
      const st: RegionState | undefined = frameStates?.[id] ?? states[id]?.state;
      const visibleLayer = id === "skin" ? layers.skin : layers[layer];
      const isolatedOut = isolate && selected && id !== selected;
      m.visible = Boolean(visibleLayer) && !(isolatedOut && id !== "skin");
      if (id === "skin") {
        m.visible = layers.skin && !(isolate && selected && selected !== "skin");
        mat.opacity = skinOpacity;
        mat.depthWrite = skinOpacity > 0.95;
        // body-wide radiation exposure overlay: tints the skin surface only (no organ claims)
        if (layers.radiation && radiation) {
          const k = Math.min(1, radiation.intensity) * (radiation.spe ? p : 0.6);
          mat.emissive.set("#8f63d9"); mat.emissiveIntensity = 0.15 + 0.6 * k;
          if (!layers.skin) { m.visible = true; mat.opacity = 0.12; mat.depthWrite = false; }
        } else { mat.emissiveIntensity = 0; }
        m.raycast = skinOpacity < 0.6 ? () => null : THREE.Mesh.prototype.raycast;
        continue;
      }
      const base = m.userData.base as THREE.Color;
      let color = base.clone();
      let emissive = new THREE.Color("#000000");
      let ei = 0;
      let opacity = 1;
      if (layers.risk && st) {
        if (st === "not_monitored") { color = base.clone().lerp(new THREE.Color("#4d4d48"), 0.75); opacity = 0.55; }
        else if (st === "unknown") { color = new THREE.Color(STATE_COLOR.unknown); }
        else if (st === "normal") { emissive = new THREE.Color(STATE_COLOR.normal); ei = 0.18; }
        else {
          color = base.clone().lerp(new THREE.Color(STATE_COLOR[st]), 0.65);
          emissive = new THREE.Color(STATE_COLOR[st]);
          ei = st === "critical" ? 0.35 + 0.65 * p : st === "elevated" ? 0.45 : 0.3;
        }
      }
      if (showEvidence && states[id]?.research_evidence?.length) { emissive = new THREE.Color("#8b6cd9"); ei = Math.max(ei, 0.45); }
      if (id === hovered || id === selected) { emissive = emissive.clone().lerp(new THREE.Color("#ffffff"), 0.35); ei = Math.max(ei, 0.35); }
      if (isolate && selected && id !== selected) opacity = 0.06;
      mat.color.copy(color); mat.emissive.copy(emissive); mat.emissiveIntensity = ei;
      mat.opacity = opacity; mat.depthWrite = opacity > 0.95;
    }
  });

  const over = (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); onHover(e.object.userData.regionId ?? null); };
  const click = (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect(e.object.userData.regionId ?? null); };
  return (
    <group>
      <primitive object={scene} onPointerOver={over} onPointerOut={() => onHover(null)} onClick={click} />
      <Labels metaById={metaById} states={states} frameStates={frameStates} hovered={hovered} selected={selected} layers={layers} />
    </group>
  );
}

// push lateral labels outward (left/right organs) and midline ones up, so neighbouring tags don't collide
function labelPos(m: RegionMeta): [number, number, number] {
  const [x, y, z] = m.center;
  if (Math.abs(x) > 0.03) return [x + Math.sign(x) * m.size[0] * 0.55, y + m.size[1] * 0.15, z];
  return [x, y + m.size[1] * 0.5, z + m.size[2] * 0.5];
}

function Labels({ metaById, states, frameStates, hovered, selected, layers }: {
  metaById: Record<string, RegionMeta>; states: Record<string, RegionInfo>; frameStates?: Record<string, RegionState> | null;
  hovered: string | null; selected: string | null; layers: Record<LayerKey, boolean>;
}) {
  const shown = Object.values(metaById).filter((m) => {
    if (m.id === "skin") return false;
    const st = frameStates?.[m.id] ?? states[m.id]?.state;
    const alert = layers.risk && st && ["observation", "elevated", "critical"].includes(st);
    return m.id === hovered || m.id === selected || alert;
  });
  return (
    <>
      {shown.map((m) => {
        const st = (frameStates?.[m.id] ?? states[m.id]?.state) as RegionState | undefined;
        const alert = st && ["observation", "elevated", "critical"].includes(st);
        return (
          <Html key={m.id} position={labelPos(m)} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
            <div className={`tag3d ${alert ? `tag-${st}` : ""}`}>
              <b>{m.label}</b>{alert && st ? <span> · {STATE_LABEL[st]}</span> : null}
            </div>
          </Html>
        );
      })}
    </>
  );
}

function CameraRig({ view, metaById, controls }: { view: Props["view"]; metaById: Record<string, RegionMeta>;
  controls: MutableRefObject<CameraControls | null> }) {
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const t: [number, number, number] = [0, 0.95, 0];
    const d = 3.1;
    if (view.key === "focus" && view.region && metaById[view.region]) {
      const m = metaById[view.region];
      const dist = Math.max(0.95, Math.max(...m.size) * 3.4);
      c.setLookAt(m.center[0] + dist * 0.25, m.center[1] + dist * 0.1, m.center[2] + dist, m.center[0], m.center[1], m.center[2], true);
      return;
    }
    const pos: Record<string, [number, number, number]> = {
      front: [0, 1.05, d], back: [0, 1.05, -d], left: [d, 1.05, 0], right: [-d, 1.05, 0], reset: [0.9, 1.25, d * 0.95],
    };
    const p = pos[view.key] ?? pos.reset;
    c.setLookAt(p[0], p[1], p[2], t[0], t[1], t[2], true);
  }, [view, metaById, controls]);
  return null;
}

export default function Body3D(props: Props) {
  const controls = useRef<CameraControls | null>(null);
  const metaById = useMemo(() => Object.fromEntries(props.regionsMeta.map((m) => [m.id, m])), [props.regionsMeta]);
  return (
    <Canvas camera={{ position: [0.9, 1.25, 2.95], fov: 38, near: 0.05, far: 50 }} dpr={[1, 2]}
      onPointerMissed={() => props.onSelect(null)} gl={{ antialias: true }}>
      <color attach="background" args={["#0e0f11"]} />
      <hemisphereLight args={["#dfe7f2", "#202022", 0.75]} />
      <directionalLight position={[2.5, 4, 3]} intensity={1.35} />
      <directionalLight position={[-3, 2, -2]} intensity={0.55} />
      <gridHelper args={[4, 20, "#2a2a28", "#1d1d1b"]} position={[0, 0, 0]} />
      <Suspense fallback={<Html center><div className="loading3d">Loading anatomy (BodyParts3D)…</div></Html>}>
        <Bvh firstHitOnly>
          <Body {...props} />
        </Bvh>
      </Suspense>
      <CameraControls ref={controls} minDistance={0.25} maxDistance={7} smoothTime={0.45} />
      <CameraRig view={props.view} metaById={metaById} controls={controls} />
    </Canvas>
  );
}

useGLTF.preload(GLB);
