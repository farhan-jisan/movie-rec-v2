import { Route, Routes } from "react-router-dom";
import AppShell from "@/components/AppShell";
import Home from "@/pages/Home";
import MovieDetail from "@/pages/MovieDetail";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/movie/:id" element={<MovieDetail />} />
        <Route path="*" element={<Home />} />
      </Routes>
    </AppShell>
  );
}
