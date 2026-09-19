import { useEffect } from "react";

interface Props {
  message: string;
  type: "success" | "warning" | "error";
  onDismiss: () => void;
}

export default function Toast({ message, type, onDismiss }: Props) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  const colors = {
    success: "border-emerald-500/30 bg-emerald-500/10",
    warning: "border-yellow-500/30 bg-yellow-500/10",
    error: "border-red-500/30 bg-red-500/10",
  };

  return (
    <div
      onClick={onDismiss}
      className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl border ${colors[type]} backdrop-blur-sm max-w-sm text-sm font-medium animate-slide-down cursor-pointer active:opacity-70 transition-opacity`}
    >
      {message}
    </div>
  );
}
