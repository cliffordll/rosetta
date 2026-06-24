import { PanelLeftClose, PanelLeft } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation } from "react-router";

import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "@/routes";

export function Nav() {
  const [collapsed, setCollapsed] = useState(false);
  const toggle = () => setCollapsed((c) => !c);
  const { pathname } = useLocation();

  return (
    <aside
      className={cn(
        "shrink-0 border-r border-border bg-card/50 px-4 py-6 transition-[width] duration-200 flex flex-col",
        collapsed ? "w-16" : "w-56",
      )}
    >
      <div className="mb-6 flex items-center justify-between">
        {!collapsed && (
          <span className="px-2 text-lg font-semibold tracking-tight">Rosetta</span>
        )}
        <button
          type="button"
          onClick={toggle}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.path);
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                "rounded-md px-3 py-2 text-sm transition-colors flex items-center gap-2.5 relative",
                collapsed && "justify-center px-2",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-accent-foreground",
              )}
              title={collapsed ? item.label : undefined}
            >
              {isActive && !collapsed && (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-primary" />
              )}
              <item.icon className="size-4 shrink-0" />
              {!collapsed && item.label}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
