import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useProfile } from "./ProfileContext";

// Orbis' compact procedural silk shader; no external demo source is bundled.
const vertex = `#version 300 es
in vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }`;

const fragment = `#version 300 es
precision highp float;
uniform vec2 resolution;
uniform float time;
out vec4 color;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), f.x),
             mix(hash(i + vec2(0., 1.)), hash(i + 1.), f.x), f.y);
}
float field(vec2 p) {
  return noise(p) * .57 + noise(p * 2.17) * .29 + noise(p * 4.31) * .14;
}
void main() {
  vec2 uv = gl_FragCoord.xy / resolution;
  float x = uv.x, y = uv.y;
  float drift = time * .03;
  float largeFold = field(vec2(x * 2.6 + drift, .4));
  float fineFold = field(vec2(x * 8.5 - drift * .7, 2.1));
  float horizon = .47 + .09 * sin(x * 4.6 + .25 + drift * .4)
                 + .04 * sin(x * 9.8 - 1.4 - drift * .3)
                 + (largeFold - .5) * .1;
  float distanceToFold = y - horizon;
  float veil = exp(-pow(distanceToFold / .16, 2.0));
  float softBody = exp(-pow((distanceToFold - .05) / .26, 2.0));
  float lowerFold = horizon - .13 + .025 * sin(x * 11. + drift * .4);
  float secondVeil = exp(-pow((y - lowerFold) / .11, 2.0));
  // Folds run along the ribbon like the orbit mark's swoosh; vertical ribs read as an audio spectrum.
  float ribbon = .5 + .5 * sin(distanceToFold * 46. + largeFold * 5. + x * 2.);
  float sheen = ribbon * ribbon * ribbon;
  float folds = (.34 + sheen * .58) * veil;
  float seam = exp(-pow(distanceToFold / .03, 2.0));
  vec3 ink = mix(vec3(.018, .028, .04), vec3(.02, .045, .066), y * .7);
  vec3 deep = vec3(.03, .14, .19);
  vec3 teal = vec3(.10, .42, .45);
  vec3 blue = vec3(.06, .22, .44);
  float hue = .5 + .5 * sin(x * 4.2 + largeFold * 3.);
  vec3 light = mix(deep, mix(teal, blue, hue * .6), .55 + .3 * fineFold);
  vec3 result = ink + light * (folds * .55 + veil * .14 + secondVeil * .09 + softBody * .07 + seam * .08);
  float vignette = smoothstep(-.18, .24, x) * smoothstep(-.18, .24, 1. - x)
                 * smoothstep(-.3, .25, y) * smoothstep(-.18, .18, 1. - y);
  result *= mix(.55, 1., vignette);
  float grain = hash(gl_FragCoord.xy + vec2(time * .7)) - .5;
  result += grain * .003;
  color = vec4(result, 1.);
}`;

function compile(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader;
  gl.deleteShader(shader);
  return null;
}

export default function OrbisSilkBackground() {
  const path = useLocation().pathname;
  const { profile } = useProfile();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [available, setAvailable] = useState(true);
  const context = path.startsWith("/watch/") ? "player" : path.startsWith("/admin") ? "admin" : !profile || path.startsWith("/profiles/") ? "open" : path.startsWith("/movie/") || path.startsWith("/tv/") ? "detail" : "browse";

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const layer = element.parentElement;
    const gl = element.getContext("webgl2", { alpha: false, antialias: false, depth: false, powerPreference: "low-power" });
    if (!gl) { setAvailable(false); return; }
    const vert = compile(gl, gl.VERTEX_SHADER, vertex);
    const frag = compile(gl, gl.FRAGMENT_SHADER, fragment);
    if (!vert || !frag) { setAvailable(false); return; }
    const program = gl.createProgram();
    if (!program) { setAvailable(false); return; }
    gl.attachShader(program, vert);
    gl.attachShader(program, frag);
    gl.linkProgram(program);
    gl.deleteShader(vert);
    gl.deleteShader(frag);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { gl.deleteProgram(program); setAvailable(false); return; }
    const buffer = gl.createBuffer();
    if (!buffer) { gl.deleteProgram(program); setAvailable(false); return; }
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.useProgram(program);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const dimensions = gl.getUniformLocation(program, "resolution");
    const clock = gl.getUniformLocation(program, "time");
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let last = -100;
    const started = performance.now();
    let stopped = false;
    function lost(event: Event) { event.preventDefault(); stopped = true; cancelAnimationFrame(frame); setAvailable(false); }
    function paint(now: number) {
      if (stopped || document.hidden || layer?.classList.contains("orbis-silk--player")) return;
      if (now - last >= 40 || motion.matches) {
        last = now;
        gl!.viewport(0, 0, element!.width, element!.height);
        gl!.uniform2f(dimensions, element!.width, element!.height);
        gl!.uniform1f(clock, motion.matches ? 0 : (now - started) / 1000 * .8);
        gl!.drawArrays(gl!.TRIANGLES, 0, 3);
      }
      if (!motion.matches) frame = requestAnimationFrame(paint);
    }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5, 1920 / window.innerWidth, 1080 / window.innerHeight);
      const width = Math.max(1, Math.round(window.innerWidth * dpr));
      const height = Math.max(1, Math.round(window.innerHeight * dpr));
      if (element!.width !== width || element!.height !== height) { element!.width = width; element!.height = height; }
      cancelAnimationFrame(frame);
      if (!document.hidden && !layer?.classList.contains("orbis-silk--player")) frame = requestAnimationFrame(paint);
    }
    function visibility() { cancelAnimationFrame(frame); if (!document.hidden && !layer?.classList.contains("orbis-silk--player")) frame = requestAnimationFrame(paint); }
    const observer = new ResizeObserver(resize);
    observer.observe(document.documentElement);
    const routeObserver = new MutationObserver(visibility);
    if (layer) routeObserver.observe(layer, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", visibility);
    element.addEventListener("webglcontextlost", lost);
    motion.addEventListener("change", resize);
    resize();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      routeObserver.disconnect();
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", visibility);
      element.removeEventListener("webglcontextlost", lost);
      motion.removeEventListener("change", resize);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, []);

  return <div className={`orbis-silk orbis-silk--${context} ${available ? "" : "orbis-silk--fallback"}`} aria-hidden="true" data-renderer={available ? "webgl" : "css"}><canvas ref={canvas} /></div>;
}
