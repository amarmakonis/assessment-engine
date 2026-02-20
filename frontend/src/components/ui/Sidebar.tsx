import { clsx } from "clsx";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Upload,
  FileText,
  Brain,
  ClipboardCheck,
  LogOut,
  Zap,
  BookOpen,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/exams", icon: BookOpen, label: "Exams" },
  { to: "/upload", icon: Upload, label: "Upload Scripts" },
  { to: "/scripts", icon: FileText, label: "Scripts" },
  { to: "/evaluations", icon: Brain, label: "Evaluations" },
  { to: "/review", icon: ClipboardCheck, label: "Review Queue" },
];

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { user, logout } = useAuth();

  return (
    <>
      {/* Overlay on mobile */}
      <div
        className={clsx(
          "fixed inset-0 bg-black/40 z-40 lg:hidden transition-opacity duration-300",
          isOpen ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sidebar - dark blue like TalentTrack Pro */}
      <aside
        className={clsx(
          "fixed left-0 top-0 z-50 h-screen w-64 flex-col bg-sidebar-dark shadow-sidebar",
          "flex transform transition-transform duration-300 ease-in-out",
          "lg:translate-x-0",
          isOpen ? "translate-x-0" : "-translate-x-full",
          "lg:translate-x-0"
        )}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between p-5 border-b border-white/10">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-accent-blue flex items-center justify-center">
                <Zap className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="font-display font-bold text-base text-white">
                  Assessment Engine
                </h1>
                <p className="text-[11px] text-white/70">by Makonis.ai</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="lg:hidden p-2 rounded-lg text-white/80 hover:bg-white/10 hover:text-white transition-colors"
              aria-label="Close menu"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={onClose}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 px-3 py-3 rounded-lg text-[15px] font-medium transition-all duration-200",
                    "border-l-4 border-transparent",
                    isActive
                  ? "bg-sidebar-dark-active/30 text-white border-l-sidebar-dark-active"
                  : "text-white/90 hover:bg-sidebar-dark-hover hover:text-white border-l-transparent"
                  )
                }
              >
                <item.icon className="w-5 h-5 flex-shrink-0" />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="p-4 border-t border-white/10">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-accent-blue flex items-center justify-center text-sm font-bold text-white">
                {user?.fullName?.charAt(0) ?? "U"}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-white truncate">{user?.fullName}</p>
                <p className="text-[11px] text-white/70 truncate">{user?.role}</p>
              </div>
            </div>
            <button
              onClick={logout}
              className="flex items-center gap-2 text-sm text-white/80 hover:text-white hover:bg-white/10 w-full px-3 py-2 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export function SidebarToggle({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="lg:hidden fixed top-4 left-4 z-30 p-2.5 rounded-lg bg-sidebar-dark text-white shadow-lg hover:bg-sidebar-dark-hover transition-colors"
      aria-label="Open menu"
    >
      <Menu className="w-6 h-6" />
    </button>
  );
}
