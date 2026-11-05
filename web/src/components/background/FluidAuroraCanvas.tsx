import React, { useEffect, useRef } from 'react';

interface Blob {
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  radius: number;
  color: string;
  speed: number;
  angle: number;
}

interface EmbeddingParticle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
  sourceType: string;
  pulsePhase: number;
}

interface FluidAuroraCanvasProps {
  isActive?: boolean;
}

const particleColors = [
  '#f59e0b', // Hugging Face amber
  '#10b981', // GitHub emerald
  '#a855f7', // ArXiv purple
  '#38bdf8', // LMSys Arena sky
  '#818cf8', // Core precision indigo
];

export const FluidAuroraCanvas: React.FC<FluidAuroraCanvasProps> = ({
  isActive = true,
}) => {
  const auroraCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const meshCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const mouse = useRef<{ x: number; y: number; targetX: number; targetY: number }>({
    x: 0,
    y: 0,
    targetX: 0,
    targetY: 0,
  });

  useEffect(() => {
    const auroraCanvas = auroraCanvasRef.current;
    const meshCanvas = meshCanvasRef.current;
    if (!auroraCanvas || !meshCanvas) return;

    const auroraCtx = auroraCanvas.getContext('2d', { alpha: true });
    const meshCtx = meshCanvas.getContext('2d', { alpha: true });
    if (!auroraCtx || !meshCtx) return;

    let width = (auroraCanvas.width = meshCanvas.width = window.innerWidth);
    let height = (auroraCanvas.height = meshCanvas.height = window.innerHeight);

    const onResize = () => {
      if (!auroraCanvas || !meshCanvas) return;
      width = auroraCanvas.width = meshCanvas.width = window.innerWidth;
      height = auroraCanvas.height = meshCanvas.height = window.innerHeight;
      initBlobs();
      initParticles();
    };
    window.addEventListener('resize', onResize);

    const onMouseMove = (e: MouseEvent) => {
      mouse.current.targetX = e.clientX;
      mouse.current.targetY = e.clientY;
    };
    window.addEventListener('mousemove', onMouseMove);

    // =========================================================================
    // 1. ИНИЦИАЛИЗАЦИЯ СЕВЕРНОГО СИЯНИЯ (СЛОЙ ГЛУБОКОГО СВЕТА)
    // =========================================================================
    let blobs: Blob[] = [];
    const initBlobs = () => {
      blobs = [
        {
          x: width * 0.25,
          y: height * 0.25,
          baseX: width * 0.25,
          baseY: height * 0.25,
          radius: Math.min(width, height) * 0.5,
          color: 'rgba(99, 102, 241, 0.18)', // Deep Indigo
          speed: 0.0007,
          angle: 0,
        },
        {
          x: width * 0.75,
          y: height * 0.35,
          baseX: width * 0.75,
          baseY: height * 0.35,
          radius: Math.min(width, height) * 0.55,
          color: 'rgba(168, 85, 247, 0.15)', // Electric Violet
          speed: 0.0009,
          angle: Math.PI / 2,
        },
        {
          x: width * 0.5,
          y: height * 0.75,
          baseX: width * 0.5,
          baseY: height * 0.75,
          radius: Math.min(width, height) * 0.6,
          color: 'rgba(14, 165, 233, 0.14)', // Radiant Sky Blue
          speed: 0.0008,
          angle: Math.PI,
        },
        {
          x: width * 0.85,
          y: height * 0.8,
          baseX: width * 0.85,
          baseY: height * 0.8,
          radius: Math.min(width, height) * 0.42,
          color: 'rgba(245, 158, 11, 0.09)', // Warm Amber Glow
          speed: 0.0012,
          angle: Math.PI * 1.5,
        },
      ];
    };

    // =========================================================================
    // 2. ИНИЦИАЛИЗАЦИЯ ВАРИАНТА Б: ЗВЕЗДНАЯ ПАУТИНА ЭМБЕДДИНГОВ (K-NN GRAPH)
    // =========================================================================
    let particles: EmbeddingParticle[] = [];
    const particleCount = Math.floor(Math.min(width, 2560) / 18); // ~95-115 четких узлов

    const initParticles = () => {
      particles = [];
      for (let i = 0; i < particleCount; i++) {
        const color = particleColors[i % particleColors.length];
        particles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.45,
          vy: (Math.random() - 0.5) * 0.45,
          radius: Math.random() * 1.5 + 1.8,
          color,
          sourceType: ['HF', 'GH', 'ArXiv', 'Arena', 'Core'][i % 5],
          pulsePhase: Math.random() * Math.PI * 2,
        });
      }
    };

    initBlobs();
    initParticles();

    let animId: number;

    const render = (time: number) => {
      // Инерция координат курсора (LERP)
      mouse.current.x += (mouse.current.targetX - mouse.current.x) * 0.08;
      mouse.current.y += (mouse.current.targetY - mouse.current.y) * 0.08;

      // -----------------------------------------------------------------------
      // 1. ОТРИСОВКА СЕВЕРНОГО СИЯНИЯ (Мягкие глубинные переливы без спотлайтов)
      // -----------------------------------------------------------------------
      auroraCtx.clearRect(0, 0, width, height);

      blobs.forEach((b) => {
        b.angle += b.speed;
        const offsetX = Math.cos(b.angle * 1.2) * (width * 0.14);
        const offsetY = Math.sin(b.angle) * (height * 0.14);

        // Чисто гармонический дрейф: убираем смещение мыши, чтобы не создавать паразитный круговой градиент
        b.x = b.baseX + offsetX;
        b.y = b.baseY + offsetY;

        const grad = auroraCtx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.radius);
        grad.addColorStop(0, b.color);
        grad.addColorStop(0.5, b.color.replace(/[\d\.]+\)$/, '0.06)'));
        grad.addColorStop(1, 'rgba(7, 7, 10, 0)');

        auroraCtx.fillStyle = grad;
        auroraCtx.beginPath();
        auroraCtx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
        auroraCtx.fill();
      });

      // -----------------------------------------------------------------------
      // 2. ОТРИСОВКА ЗВЕЗДНОЙ ПАУТИНЫ ЭМБЕДДИНГОВ (K-NN GRAPH)
      // -----------------------------------------------------------------------
      meshCtx.clearRect(0, 0, width, height);

      const tSec = time * 0.001;
      const highlightRadius = 180;
      const maxConnectDist = 150;

      // 1. Свободный гармонический дрейф узлов (100% стабильность, без выталкивания мышью)
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        if (p.x < -20) p.x = width + 20;
        else if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20;
        else if (p.y > height + 20) p.y = -20;
      }

      // 2. Отрисовка динамических межнейронных связей (k-NN Graph)
      for (let i = 0; i < particles.length; i++) {
        const p1 = particles[i];

        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j];
          const dx = p1.x - p2.x;
          const dy = p1.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < maxConnectDist) {
            const midX = (p1.x + p2.x) * 0.5;
            const midY = (p1.y + p2.y) * 0.5;
            const mDist = Math.hypot(mouse.current.x - midX, mouse.current.y - midY);
            const mouseProximity = Math.max(0, 1 - mDist / highlightRadius);

            const baseAlpha = (1 - dist / maxConnectDist) * 0.38;
            const finalAlpha = Math.min(0.9, baseAlpha + mouseProximity * 0.40);

            meshCtx.strokeStyle =
              mouseProximity > 0.05
                ? `rgba(165, 180, 252, ${finalAlpha})`
                : `rgba(180, 195, 255, ${finalAlpha})`;
            meshCtx.lineWidth = 1.0 + mouseProximity * 0.6;
            meshCtx.beginPath();
            meshCtx.moveTo(p1.x, p1.y);
            meshCtx.lineTo(p2.x, p2.y);
            meshCtx.stroke();
          }
        }
      }

      // 3. Отрисовка светящихся узлов-звезд (синаптическая активация под курсором)
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        const pulse = Math.sin(tSec * 2.5 + p.pulsePhase) * 0.25 + 1.0;

        const mDist = Math.hypot(mouse.current.x - p.x, mouse.current.y - p.y);
        const mouseProximity = Math.max(0, 1 - mDist / highlightRadius);
        const scale = 1.0 + mouseProximity * 0.35;

        // Внешнее мягкое свечение
        meshCtx.fillStyle = p.color;
        meshCtx.globalAlpha = 0.45 + mouseProximity * 0.35;
        meshCtx.beginPath();
        meshCtx.arc(p.x, p.y, p.radius * pulse * scale * 2.8, 0, Math.PI * 2);
        meshCtx.fill();

        // Яркое ядро узла
        meshCtx.globalAlpha = 1.0;
        meshCtx.beginPath();
        meshCtx.arc(p.x, p.y, p.radius * pulse * scale, 0, Math.PI * 2);
        meshCtx.fill();
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('mousemove', onMouseMove);
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <div
      className={`fixed inset-0 pointer-events-none z-0 overflow-hidden transition-opacity duration-500 ${
        isActive ? 'opacity-100' : 'opacity-0'
      }`}
    >
      {/* 1. Слой северного сияния (мягкое размытие на глубине) */}
      <canvas
        ref={auroraCanvasRef}
        className="absolute inset-0 blur-[70px] opacity-85 transition-opacity duration-1000"
      />

      {/* 2. Слой ВАРИАНТА Б: Звездная паутина эмбеддингов (четкие линии и узлы нейросети) */}
      <canvas
        ref={meshCanvasRef}
        className="absolute inset-0 opacity-90 pointer-events-none"
      />

      {/* 3. Тонкая архитектурная сетка созвездий (микро-точки 24x24px) */}
      <div
        className="absolute inset-0 opacity-[0.035] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(rgba(255, 255, 255, 0.7) 1px, transparent 1px)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* 4. Глубокая виньетка по краям */}
      <div className="absolute inset-0 bg-radial from-transparent via-[#07070a]/40 to-[#07070a] pointer-events-none" />
    </div>
  );
};
