import { FileCog, LayoutDashboard, Server, MessageSquare, ScrollText } from "lucide-react";
import { Navigate, Route, Routes } from "react-router";

import Chat from "@/pages/Chat";
import Dashboard from "@/pages/Dashboard";
import Logs from "@/pages/Logs";
import Setup from "@/pages/Setup";
import Upstreams from "@/pages/Upstreams";

export const NAV_ITEMS = [
  { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { path: "/upstreams", label: "Upstreams", icon: Server },
  { path: "/chat", label: "Chat", icon: MessageSquare },
  { path: "/setup", label: "Setup", icon: FileCog },
  { path: "/logs", label: "Logs", icon: ScrollText },
] as const;

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/upstreams" element={<Upstreams />} />
      <Route path="/setup" element={<Setup />} />
      <Route path="/logs" element={<Logs />} />
      <Route path="/chat" element={<Chat />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
