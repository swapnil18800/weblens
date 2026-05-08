import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useChat } from "./state/chatStore";
import ChatPage from "./pages/ChatPage";
import EvalPage from "./pages/EvalPage";

export default function App() {
  const init = useChat((s) => s.init);
  const devMode = useChat((s) => s.devMode);

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/eval" element={devMode ? <EvalPage /> : <Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
