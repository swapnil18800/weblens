import { useChat } from "../state/chatStore";
import Header from "../components/Header";
import Sidebar from "../components/Sidebar";
import ChatThread from "../components/ChatThread";
import ChatInput from "../components/ChatInput";
import Hero from "../components/Hero";

export default function ChatPage() {
  const turns = useChat((s) => s.turns);
  const loadingSessionId = useChat((s) => s.loadingSessionId);
  const empty = turns.length === 0 && !loadingSessionId;
  const loading = !!loadingSessionId;

  return (
    <div className="h-full flex flex-col">
      <Header />
      <div className="flex-1 flex overflow-hidden relative">
        <Sidebar />
        <main className="flex-1 flex flex-col overflow-hidden relative">
          {loading ? (
            <>
              <ChatThread />
              <ChatInput />
            </>
          ) : empty ? (
            <>
              <Hero />
              <ChatInput />
            </>
          ) : (
            <>
              <ChatThread />
              <ChatInput />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
