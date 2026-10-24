import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: P) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const ArrowLeft = (p: P) => (
  <Svg {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Svg>
);
export const ArrowRight = (p: P) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);
export const External = (p: P) => (
  <Svg {...p}>
    <path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
  </Svg>
);
export const Spark = (p: P) => (
  <Svg {...p}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />
  </Svg>
);
export const Newspaper = (p: P) => (
  <Svg {...p}>
    <path d="M4 5h13v14H6a2 2 0 0 1-2-2V5zM17 9h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5" />
  </Svg>
);
export const Bank = (p: P) => (
  <Svg {...p}>
    <path d="M3 10 12 4l9 6M5 10v8M19 10v8M9 10v8M15 10v8M3 20h18" />
  </Svg>
);
export const Chart = (p: P) => (
  <Svg {...p}>
    <path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6" />
  </Svg>
);
export const Building = (p: P) => (
  <Svg {...p}>
    <path d="M5 20V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15M15 9h3a1 1 0 0 1 1 1v10M3 20h18M8 8h3M8 12h3M8 16h3" />
  </Svg>
);
export const Text = (p: P) => (
  <Svg {...p}>
    <path d="M5 6h14M5 10h14M5 14h9M5 18h6" />
  </Svg>
);
export const Chat = (p: P) => (
  <Svg {...p}>
    <path d="M5 18l-1 3 4-2h9a3 3 0 0 0 3-3V8a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v7a3 3 0 0 0 1 3z" />
  </Svg>
);
export const Check = (p: P) => (
  <Svg {...p}>
    <path d="M5 12l5 5 9-10" />
  </Svg>
);
export const Dot = ({ color, size = 8 }: { color: string; size?: number }) => (
  <span
    aria-hidden="true"
    style={{ display: 'inline-block', width: size, height: size, borderRadius: size, background: color }}
  />
);
