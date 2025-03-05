import { useState } from "react";
import { useNavigate } from "react-router-dom";

function RegisterPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg("");

    try {
      const res = await fetch("http://localhost:8000/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });

      if (!res.ok) {
        throw new Error(`Register failed: ${res.status}`);
      }
      const data = await res.json();
      setMsg("Register success: " + JSON.stringify(data));

      // 회원가입 성공 후 /login 이동
      navigate("/login");
    } catch (error: any) {
      console.error(error);
      setMsg(error.message);
    }
  };

  const handleCancel = () => {
    navigate("/login");
  };

  return (
    <div style={{ margin: "2rem" }}>
      <h2>Register</h2>
      <form onSubmit={handleRegister}>
        <div>
          <label>Username: </label>
          <input 
            value={username} 
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div>
          <label>Password: </label>
          <input 
            type="password" 
            value={password} 
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit">Register</button>
        <button type="button" onClick={handleCancel}>Cancel</button>
      </form>
      {msg && <p>{msg}</p>}
    </div>
  );
}

export default RegisterPage;
