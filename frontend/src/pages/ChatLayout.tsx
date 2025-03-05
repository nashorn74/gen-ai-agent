import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

interface Message {
  message_id: number;
  role: string;
  content: string;
  created_at: string;
}

function ChatLayout() {
  const navigate = useNavigate();
  const [userName, setUserName] = useState("");
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number | null>(null);

  const [messages, setMessages] = useState<Message[]>([]); // 대화 메시지 목록
  const [question, setQuestion] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    // /auth/me
    fetch("http://localhost:8000/auth/me", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => { setUserName(data.username); })
      .catch(err => console.error("Failed to get me:", err));

    // 대화 목록
    fetch("http://localhost:8000/chat/conversations", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => setConversations(data))
      .catch(err => console.error("Failed to get convos:", err));
  }, []);

  // 대화 선택이 바뀔 때마다, 대화 상세를 불러옴
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    if (!selectedConversation) {
      setMessages([]);
      return;
    }

    fetch(`http://localhost:8000/chat/conversations/${selectedConversation}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : Promise.reject(res.statusText))
      .then(data => {
        // data.messages = [{message_id, role, content, created_at}...]
        setMessages(data.messages);
      })
      .catch(err => console.error("Failed to get conv detail:", err));
  }, [selectedConversation]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  // 질문 전송
  const handleAsk = async () => {
    const token = localStorage.getItem("token");
    if (!token) return;

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          conversation_id: selectedConversation,
          question
        })
      });
      if (!res.ok) {
        throw new Error(`Chat error: ${res.status}`);
      }
      const data = await res.json();

      // 새 메시지 추가( user + assistant )
      const newAssistantMsg = {
        message_id: Date.now(), 
        role: "assistant",
        content: data.answer,
        created_at: new Date().toISOString()
      };
      const newUserMsg = {
        message_id: Date.now() + 1,
        role: "user",
        content: question,
        created_at: new Date().toISOString()
      };

      if (!data.conversation_id) {
        // fallback
        console.error("No conversation id from server??");
      } else {
        setSelectedConversation(data.conversation_id);
      }
      
      // 실제 서버에선 conversation detail API 다시 불러와도 되지만,
      // 여기서는 클라이언트 측 state로 간단히
      setMessages([...messages, newUserMsg, newAssistantMsg]);
      setQuestion("");
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Left sidebar: conversation list */}
      <div style={{ width: "200px", borderRight: "1px solid #ccc", padding: "1rem" }}>
        <h4>Conversations</h4>
        <ul style={{ listStyle: "none", padding: 0 }}>
          {conversations.map((c) => (
            <li
              key={c.conversation_id}
              style={{
                cursor: "pointer",
                backgroundColor: c.conversation_id === selectedConversation ? "#ddd" : "transparent",
                margin: "5px 0",
                padding: "5px"
              }}
              onClick={() => setSelectedConversation(c.conversation_id)}
            >
              {c.title || `Conv ${c.conversation_id}`}
            </li>
          ))}
        </ul>
      </div>

      {/* Right panel: top bar + messages */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Top bar with user name and logout */}
        <div style={{ height: "50px", borderBottom: "1px solid #ccc", display: "flex", justifyContent: "flex-end", alignItems: "center", padding: "0 1rem" }}>
          <span style={{ marginRight: "1rem" }}>{userName}</span>
          <button onClick={handleLogout}>Logout</button>
        </div>

        {/* Chat area */}
        <div style={{ flex: 1, padding: "1rem" }}>
          {!selectedConversation && (
            <p>Select a conversation or ask a question to start a new one.</p>
          )}

          {selectedConversation && (
            <>
              {/* 메시지 목록을 채팅 형태로 표시 */}
              <div style={{ marginBottom: "1rem", border: "1px solid #ccc", padding: "5px", height: "60vh", overflowY: "auto" }}>
                {messages.map((m) => (
                  <div key={m.message_id} style={{ margin: "5px 0" }}>
                    <strong>{m.role}:</strong> {m.content}
                  </div>
                ))}
              </div>

              {/* 질문 입력 */}
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  style={{ flex: 1 }}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask something..."
                />
                <button onClick={handleAsk}>Send</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default ChatLayout;
