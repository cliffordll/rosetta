import { Nav } from "@/components/Nav";
import { AppRoutes } from "@/routes";

export default function App() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Nav />
      <main className="flex-1 px-10 py-8">
        <AppRoutes />
      </main>
    </div>
  );
}
