"use client";

import { useEffect, useRef, useState } from "react";

type Clip = { start: number; end: number; score: number; title: string; reason: string; filename: string; url: string };
type Result = { highlights: Clip[]; filename: string };
type Job = { job_id: string; status: "queued" | "processing" | "done" | "error"; stage: string; clips_done: number; clips_total: number; result?: Result; error?: string };
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const formats = ["original", "16:9", "9:16", "1:1"];
const types = ["auto", "podcast", "sports", "vlog", "interview", "speech"];
const stages = [
  ["extracting", "Extracting audio"],
  ["transcribing", "Transcribing speech"],
  ["analyzing", "Finding best moments"],
  ["rendering", "Rendering clips + captions"],
  ["storing", "Saving clips to Supabase"],
];
const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export default function Studio() {
  const picker = useRef<HTMLInputElement>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState("auto");
  const [count, setCount] = useState(3);
  const [length, setLength] = useState("auto");
  const [format, setFormat] = useState("9:16");
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<"idle" | "uploading" | "processing" | "done">("idle");
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [stage, setStage] = useState("queued");
  const [clipsDone, setClipsDone] = useState(0);
  const [clipsTotal, setClipsTotal] = useState(0);
  useEffect(() => {
    if (phase !== "uploading" && phase !== "processing") return;
    const timer = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);
  useEffect(() => () => xhrRef.current?.abort(), []);
  useEffect(() => {
    if (!jobId || phase !== "processing") return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(`${API}/jobs/${jobId}`, { cache: "no-store" });
        const job = await response.json() as Job;
        if (!response.ok) throw new Error(job.error || "The processing job was lost after a backend restart.");
        if (stopped) return;
        setStage(job.stage); setClipsDone(job.clips_done); setClipsTotal(job.clips_total);
        if (job.status === "done") {
          setResult(job.result || { filename: "", highlights: [] }); setPhase("done"); setJobId(null); return;
        }
        if (job.status === "error") {
          setError(job.error || "Processing failed."); setPhase("idle"); setJobId(null); return;
        }
      } catch (reason) {
        if (stopped) return;
        setError(reason instanceof Error ? reason.message : "Could not read processing progress.");
        setPhase("idle"); setJobId(null); return;
      }
      timer = setTimeout(poll, 1200);
    }
    poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [jobId, phase]);
  const busy = phase === "uploading" || phase === "processing";

  function choose(next?: File) {
    if (!next) return;
    if (!/\.(mp4|mov|mkv|webm)$/i.test(next.name)) { setError("Choose an MP4, MOV, MKV, or WebM video."); return; }
    setFile(next); setError(""); setResult(null); setPhase("idle");
  }
  function generate() {
    if (!file || busy) return;
    setError(""); setResult(null); setProgress(0); setElapsed(0); setStage("queued"); setJobId(null); setPhase("uploading");
    const form = new FormData();
    form.append("file", file); form.append("content_type", type);
    form.append("clip_count", String(count)); form.append("output_format", format);
    form.append("clip_length", length);
    const xhr = new XMLHttpRequest(); xhrRef.current = xhr;
    xhr.open("POST", `${API}/jobs`);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) setProgress(Math.round(event.loaded / event.total * 100)); };
    xhr.upload.onload = () => { setProgress(100); setPhase("processing"); };
    xhr.onload = () => {
      xhrRef.current = null;
      let data: Record<string, unknown> = {};
      try { data = JSON.parse(xhr.responseText); } catch { data = {}; }
      if (xhr.status < 200 || xhr.status >= 300) {
        setError(typeof data.detail === "string" ? data.detail : `Processing failed (HTTP ${xhr.status}).`);
        setPhase("idle"); return;
      }
      if (typeof data.job_id !== "string") {
        setError("Backend did not return a processing job ID."); setPhase("idle"); return;
      }
      setJobId(data.job_id); setPhase("processing");
    };
    xhr.onerror = () => { xhrRef.current = null; setError("Cannot reach FastAPI. Start the local backend on port 8000."); setPhase("idle"); };
    xhr.send(form);
  }

  return <div className="shell">
    <aside className="rail"><div className="logo">▣</div><div className="rail-rule" /><div className="rail-active">▦</div><div className="rail-bottom">● LOCAL</div></aside>
    <div className="workarea"><header className="topbar"><div><span>WORKSPACE</span><b>/</b> New project</div><div className="top-status"><i /> LOCAL AI ENGINE <strong>HR</strong></div></header>
      <main className="content"><div className="intro"><div><div className="eyebrow">— &nbsp; VIDEO WORKSPACE · 01</div><h1>Turn the long story<br /><em>into the moment.</em></h1><p>Upload a video. Find the strongest moments. Export clips ready to share.</p></div><div className="local-card"><i /><div><strong>Local AI · Supabase clips</strong><small>Whisper · Qwen3:4b · FFmpeg</small></div></div></div>
        <div className="columns"><section className="setup" aria-label="Create highlights">
          <div className="heading"><span>01</span><div><h2>Source video</h2><p>Bring in your long-form footage</p></div></div>
          <input type="file" hidden ref={picker} accept=".mp4,.mov,.mkv,.webm" onChange={(e) => choose(e.target.files?.[0])} />
          <div className={`drop ${dragging ? "dragging" : ""}`} role="button" tabIndex={0} onClick={() => picker.current?.click()} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") picker.current?.click(); }} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0]); }}><div className="upload-icon">↥</div><strong>{file ? file.name : "Drop your video here"}</strong><span>{file ? `${(file.size / 1048576).toFixed(1)} MB · Click to replace` : "or click to browse files"}</span><small>MP4, MOV, MKV, WEBM</small></div>
          <div className="rule" /><div className="heading"><span>02</span><div><h2>Set the direction</h2><p>Tell the editor what to look for</p></div></div>
          <label className="label" htmlFor="content-type">CONTENT TYPE</label><select id="content-type" value={type} onChange={(e) => setType(e.target.value)}>{types.map((t) => <option key={t} value={t}>{t === "auto" ? "Auto detect" : t[0].toUpperCase() + t.slice(1)}</option>)}</select>
          <div className="field-heading"><span className="label">NUMBER OF CLIPS</span><small>Select your output</small></div><div className="segmented">{[3, 5, 10].map((n) => <button type="button" className={count === n ? "selected" : ""} onClick={() => setCount(n)} key={n}>{n} clips</button>)}</div>
          <div className="field-heading formats-title"><span className="label">CLIP LENGTH</span><small>Based on transcript timing</small></div><div className="segmented">{[["auto", "Auto"], ["15-30", "15–30 sec"], ["30-60", "30–60 sec"]].map(([value, label]) => <button type="button" className={length === value ? "selected" : ""} onClick={() => setLength(value)} key={value}>{label}</button>)}</div>
          <div className="field-heading formats-title"><span className="label">OUTPUT FORMAT</span><small>Center crop for new ratios</small></div><div className="formats">{formats.map((f) => <button type="button" className={format === f ? "selected" : ""} onClick={() => setFormat(f)} key={f}><span className={`ratio ratio-${f.replace(":", "-")}`} /><strong>{f === "9:16" ? "Vertical" : f === "16:9" ? "Wide" : f === "1:1" ? "Square" : "Original"}</strong><small>{f}</small></button>)}</div>
          {error && <div className="error" role="alert">{error}</div>}<button className="generate" type="button" onClick={generate} disabled={!file || busy}><span>✦</span>{busy ? "Creating highlights…" : "Generate highlights"}<b>↗</b></button><p className="footnote">✳ &nbsp; Powered by local models. No paid API required.</p>
        </section><section className="output" aria-label="Highlight results"><div className="output-head"><div><small>YOUR OUTPUT</small><h2>{result ? "Selected moments" : "The cutting room"}</h2></div><span className={`badge ${result ? "ready" : ""}`}>{result ? `${result.highlights.length} CLIPS READY` : busy ? "IN PROGRESS" : "AWAITING VIDEO"}</span></div>
          {result ? <div className="results">{result.highlights.length === 0 && <p className="no-results">No clear highlights found. Try a longer video.</p>}{result.highlights.map((clip, i) => <article className="clip" key={clip.url}><video controls preload="metadata" src={`${API}${clip.url}`} aria-label={clip.title} /><div className="clip-copy"><div className="clip-top"><span>CLIP {String(i + 1).padStart(2, "0")}</span><span>✦ {clip.score} SCORE</span></div><h3>{clip.title}</h3><p>{clip.reason}</p><div className="clip-bottom"><span>{clock(clip.start)} — {clock(clip.end)} · {Math.round(clip.end - clip.start)} sec</span><a href={`${API}${clip.url}?download=true`}>Download ↓</a></div></div></article>)}<button className="again" onClick={() => { setFile(null); setResult(null); setPhase("idle"); if (picker.current) picker.current.value = ""; }}>＋ Start another project</button></div> : busy ? <div className="processing"><div className="orbit">✦</div><small>{phase === "uploading" ? "UPLOADING SOURCE" : "LOCAL AI AT WORK"}</small><h3>{phase === "uploading" ? "Bringing your video in." : "Finding the moments worth keeping."}</h3><p>{phase === "uploading" ? `${progress}% uploaded` : "Transcribing, selecting moments and rendering clips. Long videos can take a while on CPU."}</p><div className={`progress ${phase === "processing" ? "moving" : ""}`}><span style={phase === "uploading" ? { width: `${progress}%` } : undefined} /></div><p className="elapsed">{elapsed}s elapsed · Keep this tab open</p></div> : <div className="empty"><div className="preview"><span className="play">▶</span><div className="wave">▂ ▃ ▆ ▂ ▅ ▇ ▃ ▆ ▂ ▄ ▇ ▂ ▃ ▆ ▅ ▂ ▄</div><span className="timecode">00:00 / 00:00</span></div><div className="empty-text"><span>✦</span><h3>Your best moments live here.</h3><p>Set up a project on the left, and your finished clips will appear in this workspace.</p></div></div>}
          {busy && phase === "processing" && <div className="stage-list" aria-live="polite">{stages.map(([key, label], index) => {
            const activeIndex = stages.findIndex(([name]) => name === stage);
            return <div key={key} className={index < activeIndex ? "complete" : index === activeIndex ? "current" : "pending"}><span>{index < activeIndex ? "✓" : index + 1}</span><strong>{label}</strong>{key === "rendering" && clipsTotal > 0 && <small>{clipsDone}/{clipsTotal}</small>}</div>;
          })}</div>}
          <div className="output-foot"><span>LOCAL WORKSPACE</span><span>PRIVATE BY DESIGN <i /></span></div></section></div><footer className="footer"><span>HIGHLIGHT REEL MAKER / STUDIO</span><span>Built for the moments that matter.</span></footer>
      </main>
    </div>
  </div>;
}
