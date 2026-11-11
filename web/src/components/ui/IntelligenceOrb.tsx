import React, { useRef, useEffect } from 'react';
import { motion } from 'framer-motion';

export const IntelligenceOrb: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let frame = 0;
    let animId: number;

    const render = () => {
      frame += 0.03;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const cx = canvas.width / 2;
      const cy = canvas.height / 2;
      const r = 14;

      ctx.save();
      ctx.beginPath();
      for (let a = 0; a < Math.PI * 2; a += 0.15) {
        // Микро-пульсация квантовой сферы
        const morph = Math.sin(a * 4 + frame) * 1.8 + Math.cos(a * 3 - frame * 1.5) * 1.2;
        const currentR = r + morph;
        const x = cx + Math.cos(a) * currentR;
        const y = cy + Math.sin(a) * currentR;
        if (a === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();

      // Живой градиент внутри ядра (Apple Intelligence / Vercel style)
      const grad = ctx.createLinearGradient(
        cx + Math.cos(frame) * r,
        cy + Math.sin(frame) * r,
        cx - Math.cos(frame) * r,
        cy - Math.sin(frame) * r
      );
      grad.addColorStop(0, '#38BDF8'); // Sky Cyan
      grad.addColorStop(0.35, '#818CF8'); // Indigo
      grad.addColorStop(0.7, '#C084FC'); // Purple
      grad.addColorStop(1, '#F472B6'); // Pink Rose

      ctx.fillStyle = grad;
      ctx.shadowColor = '#818CF8';
      ctx.shadowBlur = 12;
      ctx.fill();
      ctx.restore();

      animId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animId);
  }, []);

  return (
    <div className="relative group flex items-center gap-2 cursor-pointer select-none">
      <div className="relative flex items-center justify-center">
        {/* Мягкий внешний пульсирующий ареол */}
        <div className="absolute inset-0 rounded-full bg-indigo-500/30 blur-md animate-pulse" />
        <canvas ref={canvasRef} width={38} height={38} className="w-[32px] h-[32px] relative z-10" />
      </div>

      <div className="hidden sm:flex flex-col">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-bold text-white tracking-tight">Scout Pulse</span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
        </div>
        <span className="text-[10px] font-mono text-zinc-400 flex items-center gap-1">
          <span className="text-indigo-400 font-semibold">1.48M</span> vectors live
        </span>
      </div>
    </div>
  );
};
