import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { authAPI } from "@/services/api";
import { Zap } from "lucide-react";
import toast from "react-hot-toast";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [isSignUp, setIsSignUp] = useState(false);
  const [loading, setLoading] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [institutionId, setInstitutionId] = useState("");

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch {
      toast.error("Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignUp(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await authAPI.register({
        email,
        password,
        fullName,
        institutionId,
        role: "INSTITUTION_ADMIN",
      });
      toast.success("Account created! Signing you in...");
      await login(email, password);
      navigate("/");
    } catch (err: any) {
      const msg = err?.response?.data?.message || "Registration failed";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setIsSignUp(!isSignUp);
    setEmail("");
    setPassword("");
    setFullName("");
    setInstitutionId("");
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-accent-blue flex items-center justify-center mx-auto mb-4 shadow-lg">
            <Zap className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-display font-bold text-text-primary">
            Agentic Assessment Engine
          </h1>
          <p className="text-text-secondary mt-2 text-sm">
            {isSignUp ? "Create your account" : "Sign in to your account"}
          </p>
        </div>

        <form
          onSubmit={isSignUp ? handleSignUp : handleLogin}
          className="bg-white rounded-2xl shadow-card border border-border p-8 space-y-5"
        >
          {isSignUp && (
            <>
              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1.5">
                  Full Name
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="input-field"
                  placeholder="John Doe"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-text-secondary mb-1.5">
                  Institution ID
                </label>
                <input
                  type="text"
                  value={institutionId}
                  onChange={(e) => setInstitutionId(e.target.value)}
                  className="input-field"
                  placeholder="inst_001"
                  required
                />
              </div>
            </>
          )}

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
              placeholder="you@institution.edu"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              placeholder={isSignUp ? "Min 8 characters" : "Enter your password"}
              minLength={isSignUp ? 8 : undefined}
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading
              ? isSignUp
                ? "Creating account..."
                : "Signing in..."
              : isSignUp
                ? "Create Account"
                : "Sign In"}
          </button>

          <p className="text-center text-sm text-text-secondary">
            {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
            <button
              type="button"
              onClick={switchMode}
              className="text-accent-blue hover:underline font-medium"
            >
              {isSignUp ? "Sign In" : "Sign Up"}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
