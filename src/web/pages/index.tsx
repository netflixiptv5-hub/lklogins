import { useState, useEffect, useRef } from "react";

type JobStatus = "idle" | "connecting" | "logged_in" | "searching" | "found" | "not_found" | "not_found_waiting" | "error" | "expired_waiting";

interface StatusStep {
  label: string;
  status: "pending" | "active" | "done" | "error";
}

const SERVICE_OPTIONS = [
  {
    id: "password_reset",
    title: "Redefinição de Senha Netflix",
    description: "Recuperar link de redefinição de senha",
    icon: "🔑",
    brand: "netflix",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou a redefinição de senha na Netflix?",
    confirmDetail: "Se ainda não solicitou, acesse o link abaixo e solicite antes de continuar:",
    confirmLink: "https://www.netflix.com/br/LoginHelp",
    confirmLinkText: "Solicitar Redefinição na Netflix →",
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
  {
    id: "household_update",
    title: "Atualizar Residência Netflix",
    description: "Link para atualizar residência Netflix",
    icon: "🏠",
    brand: "netflix",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já recebeu o email da Netflix sobre atualização de residência?",
    confirmDetail: "O email deve ter chegado nos últimos 15 minutos. Se não recebeu, solicite pela Netflix antes.",
    confirmLink: null,
    confirmLinkText: null,
    confirmButton: "JÁ RECEBI O EMAIL, CONTINUAR",
  },
  {
    id: "temp_code",
    title: "Código Temporário Netflix",
    description: "Código de acesso temporário (4 dígitos)",
    icon: "🔢",
    brand: "netflix",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou o código de acesso temporário na Netflix?",
    confirmDetail: "Solicite o código na Netflix antes de continuar. O código deve ter chegado nos últimos 15 minutos.",
    confirmLink: null,
    confirmLinkText: null,
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
  {
    id: "netflix_disconnect",
    title: "Desconectar Dispositivos Netflix",
    description: "Código de verificação (6 dígitos) para confirmar alteração",
    icon: "📱",
    brand: "netflix",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou a desconexão de dispositivos na Netflix?",
    confirmDetail: "Solicite a desconexão na Netflix antes de continuar. O email com o código de 6 dígitos deve ter chegado nos últimos 15 minutos.",
    confirmLink: null,
    confirmLinkText: null,
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
  {
    id: "prime_code",
    title: "Código Prime Video",
    description: "Código de verificação Amazon Prime Video",
    icon: "📺",
    brand: "prime",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou o código de verificação no Prime Video?",
    confirmDetail: "Solicite o código no Prime Video/Amazon antes de continuar.",
    confirmLink: null,
    confirmLinkText: null,
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
  {
    id: "disney_code",
    title: "Código Disney+",
    description: "Código de verificação Disney+",
    icon: "✨",
    brand: "disney",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou o código de verificação no Disney+?",
    confirmDetail: "Solicite o código no Disney+ antes de continuar.",
    confirmLink: null,
    confirmLinkText: null,
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
  {
    id: "globo_reset",
    title: "Redefinição de Senha Globoplay",
    description: "Link de redefinição de senha Globoplay",
    icon: "🌐",
    brand: "globo",
    confirmTitle: "Atenção!",
    confirmMessage: "Você já solicitou a redefinição de senha no Globoplay?",
    confirmDetail: "Se ainda não solicitou, acesse o link abaixo e solicite antes de continuar:",
    confirmLink: "https://login.globo.com/recuperacaoSenha/4728?url=https%3A%2F%2Fauthx.globoid.globo.com%2Fnot-found",
    confirmLinkText: "Solicitar Redefinição no Globoplay →",
    confirmButton: "JÁ SOLICITEI, CONTINUAR",
  },
];

export default function Index() {
  const [email, setEmail] = useState("");
  const [selectedService, setSelectedService] = useState("");
  const [jobStatus, setJobStatus] = useState<JobStatus>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [extractedLink, setExtractedLink] = useState<string | null>(null);
  const [extractedCode, setExtractedCode] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [steps, setSteps] = useState<StatusStep[]>([]);
  const [showConfirm, setShowConfirm] = useState(false);
  const [method, setMethod] = useState<string | null>(null);
  const [eta, setEta] = useState<number | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [isExpired, setIsExpired] = useState(false);
  const [savedJobId, setSavedJobId] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isValidEmail = (e: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);

  const selectedServiceData = SERVICE_OPTIONS.find((s) => s.id === selectedService);

  const updateSteps = (status: JobStatus) => {
    const baseSteps: StatusStep[] = [
      { label: "Conectando ao servidor de email...", status: "pending" },
      { label: "Email logado! Buscando seu link...", status: "pending" },
      { label: "Processando resultado...", status: "pending" },
    ];

    switch (status) {
      case "connecting":
        baseSteps[0].status = "active";
        break;
      case "logged_in":
        baseSteps[0].status = "done";
        baseSteps[1].status = "active";
        break;
      case "searching":
        baseSteps[0].status = "done";
        baseSteps[1].status = "active";
        break;
      case "found":
        baseSteps[0].status = "done";
        baseSteps[1].status = "done";
        baseSteps[2].status = "done";
        break;
      case "not_found":
        baseSteps[0].status = "done";
        baseSteps[1].status = "done";
        baseSteps[2].status = "error";
        break;
      case "error":
        baseSteps[0].status = "error";
        break;
    }
    setSteps(baseSteps);
  };

  const handleBuscar = () => {
    if (!isValidEmail(email) || !selectedService) return;
    setShowConfirm(true);
  };

  const startExtraction = async () => {
    setShowConfirm(false);
    if (!isValidEmail(email) || !selectedService) return;

    setJobStatus("connecting");
    setExtractedLink(null);
    setExtractedCode(null);
    setErrorMessage(null);
    setMethod(null);
    setEta(null);
    setElapsedSec(0);
    updateSteps("connecting");

    // Start elapsed timer (auto-error after 300s)
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsedSec((prev) => {
        if (prev + 1 > 300) {
          // 5 min timeout — assume something went wrong
          if (timerRef.current) clearInterval(timerRef.current);
          if (pollRef.current) clearInterval(pollRef.current);
          setJobStatus("error");
          setErrorMessage("Tempo limite excedido. Tente novamente.");
          updateSteps("error");
          return prev + 1;
        }
        return prev + 1;
      });
    }, 1000);

    try {
      const res = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, service: selectedService }),
      });
      const data = await res.json();

      if (!data.ok) {
        setJobStatus("error");
        setErrorMessage(data.error || "Erro ao iniciar. Tente novamente.");
        updateSteps("error");
        return;
      }

      setJobId(data.jobId);
      startPolling(data.jobId);
    } catch {
      setJobStatus("error");
      setErrorMessage("Erro de conexão. Tente novamente.");
      updateSteps("error");
    }
  };

  const startPolling = (id: string) => {
    if (pollRef.current) clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/status/${id}`);
        const data = await res.json();

        if (!data.ok) return;

        const s = data.status as JobStatus;
        setJobStatus(s);
        updateSteps(s);
        if (data.method) setMethod(data.method);
        if (data.eta !== undefined && data.eta !== null) setEta(data.eta);

        if (s === "found") {
          setExtractedLink(data.link || null);
          setExtractedCode(data.code || null);
          setIsExpired(data.expired || false);
          if (data.expired) {
            // Salva jobId para reuso e entra no modo aguardando reenvio
            setSavedJobId(id);
            setJobStatus("expired_waiting");
            if (pollRef.current) clearInterval(pollRef.current);
            if (timerRef.current) clearInterval(timerRef.current);
            return;
          }
          if (pollRef.current) clearInterval(pollRef.current);
          if (timerRef.current) clearInterval(timerRef.current);
        } else if (s === "not_found") {
          setErrorMessage(data.message || "Nenhum email encontrado nos últimos 15 minutos.");
          setJobStatus("not_found_waiting");
          if (pollRef.current) clearInterval(pollRef.current);
          if (timerRef.current) clearInterval(timerRef.current);
        } else if (s === "error") {
          setErrorMessage(data.message || "Erro ao acessar email.");
          if (pollRef.current) clearInterval(pollRef.current);
          if (timerRef.current) clearInterval(timerRef.current);
        }
      } catch {
        // retry silently
      }
    }, 2000);
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);


  const reset = () => {
    setJobStatus("idle");
    setJobId(null);
    setSavedJobId(null);
    setExtractedLink(null);
    setExtractedCode(null);
    setErrorMessage(null);
    setSteps([]);
    setEmail("");
    setSelectedService("");
    setShowConfirm(false);
    setMethod(null);
    setEta(null);
    setElapsedSec(0);
    setIsExpired(false);
    if (pollRef.current) clearInterval(pollRef.current);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  // Reenvio: já está logado, só rebusca o email sem logar de novo
  const handleReenvio = async () => {
    setExtractedLink(null);
    setExtractedCode(null);
    setErrorMessage(null);
    setMethod(null);
    setEta(null);
    setElapsedSec(0);
    setIsExpired(false);
    setJobStatus("searching");
    updateSteps("searching");

    // Start elapsed timer (auto-error after 300s)
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsedSec((prev) => {
        if (prev + 1 > 300) {
          // 5 min timeout — assume something went wrong
          if (timerRef.current) clearInterval(timerRef.current);
          if (pollRef.current) clearInterval(pollRef.current);
          setJobStatus("error");
          setErrorMessage("Tempo limite excedido. Tente novamente.");
          updateSteps("error");
          return prev + 1;
        }
        return prev + 1;
      });
    }, 1000);

    try {
      // Cria novo job — o worker vai logar de novo (já é rápido com API)
      const res = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, service: selectedService, skipLogin: true }),
      });
      const data = await res.json();
      if (!data.ok) {
        setJobStatus("error");
        setErrorMessage(data.error || "Erro ao reenviar. Tente novamente.");
        updateSteps("error");
        return;
      }
      setJobId(data.jobId);
      startPolling(data.jobId);
    } catch {
      setJobStatus("error");
      setErrorMessage("Erro de conexão. Tente novamente.");
      updateSteps("error");
    }
  };

  return (
    <div className="min-h-screen relative flex flex-col overflow-hidden">
      {/* Background image */}
      <div
        className="absolute inset-0 z-0"
        style={{
          backgroundImage: "url(/bg-netflix.jpg)",
          backgroundSize: "cover",
          backgroundPosition: "center",
          backgroundRepeat: "no-repeat",
        }}
      />
      {/* Dark overlay with gradient */}
      <div className="absolute inset-0 z-[1] bg-black/70" />
      <div className="absolute inset-0 z-[1]" style={{
        background: "linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.5) 40%, rgba(0,0,0,0.5) 60%, rgba(0,0,0,0.85) 100%)"
      }} />

      {/* Content */}
      <div className="relative z-10 flex flex-col min-h-screen">
        {/* Header */}
        <header className="w-full px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="text-[#E50914] font-black"
              style={{
                fontFamily: "'Bebas Neue', 'Impact', 'Arial Black', sans-serif",
                fontSize: "clamp(1.5rem, 5vw, 2.5rem)",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                lineHeight: 1,
              }}
            >
              LKLOGINS
            </span>
            <span className="text-white/80 text-sm font-light ml-3 hidden sm:inline">
              CÓDIGOS & LINKS
            </span>
          </div>
        </header>

        {/* Main */}
        <main className="flex-1 flex items-center justify-center px-4 py-8">
          <div className="w-full max-w-[440px]">
            {/* Card */}
            <div className="bg-black/80 backdrop-blur-md rounded-lg p-8 md:p-10 border border-white/5">
              {jobStatus === "idle" ? (
                <>
                  <h1 className="text-[28px] md:text-[32px] font-bold text-white mb-1">
                    Acessar Link
                  </h1>
                  <p className="text-[#8c8c8c] text-sm mb-6">
                    Digite seu email e selecione o serviço desejado.
                  </p>

                  {/* Email input */}
                  <div className="mb-5">
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="Email da conta"
                      className="w-full bg-[#161616] text-white rounded px-4 py-4 text-base outline-none border border-[#444] focus:border-[#E50914] transition-colors placeholder:text-[#6b6b6b]"
                    />
                  </div>

                  {/* Service selection */}
                  <div className="mb-6 space-y-2.5">
                    <label className="text-[#8c8c8c] text-sm block">Selecione o serviço:</label>
                    {SERVICE_OPTIONS.map((opt) => (
                      <button
                        key={opt.id}
                        onClick={() => setSelectedService(opt.id)}
                        className={`w-full text-left p-3.5 rounded border transition-all ${
                          selectedService === opt.id
                            ? "bg-[#E50914]/15 border-[#E50914] text-white"
                            : "bg-[#161616] border-[#333] text-[#B3B3B3] hover:border-[#555] hover:text-white"
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-xl">{opt.icon}</span>
                          <div className="flex-1">
                            <div className="font-semibold text-[14px]">{opt.title}</div>
                            <div className="text-xs text-[#777] mt-0.5">{opt.description}</div>
                          </div>
                          {selectedService === opt.id && (
                            <div className="w-5 h-5 rounded-full bg-[#E50914] flex items-center justify-center flex-shrink-0">
                              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                              </svg>
                            </div>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>

                  {/* Submit button */}
                  <button
                    onClick={handleBuscar}
                    disabled={!isValidEmail(email) || !selectedService}
                    className={`w-full py-3.5 rounded font-bold text-[15px] tracking-wide transition-all ${
                      isValidEmail(email) && selectedService
                        ? "bg-[#E50914] hover:bg-[#F40612] text-white cursor-pointer"
                        : "bg-[#333] text-[#555] cursor-not-allowed"
                    }`}
                  >
                    BUSCAR LINK
                  </button>

                  <p className="text-[#444] text-xs text-center mt-5">
                    O email deve ter sido recebido nos últimos 15 minutos.
                  </p>
                </>
              ) : (
                <>
                  {/* Processing / Result state */}
                  <div className="text-center">
                    {/* Loading */}
                    {(jobStatus === "connecting" || jobStatus === "logged_in" || jobStatus === "searching") && (
                      <div className="mb-6">
                        <div className="spinner-netflix mx-auto mb-6"></div>
                        <h2 className="text-xl font-bold text-white mb-1">Processando...</h2>
                        <p className="text-[#666] text-sm mb-2">Aguarde enquanto buscamos seu link</p>
                        
                        {/* Estimated time */}
                        <div className="bg-[#1a1a1a] rounded-lg px-4 py-3 mb-6 border border-[#222]">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-[#888]">
                              {method === "selenium" || method === "playwright" ? "⏱ Modo navegador — ~45s" : method === "imap" ? "⚡ IMAP direto — ~5s" : "⚡ Modo rápido — ~10s"}
                            </span>
                            <span className="text-white font-mono font-bold">
                              {elapsedSec}s
                            </span>
                          </div>
                          <div className="mt-2 w-full bg-[#333] rounded-full h-1.5 overflow-hidden">
                            <div
                              className="h-full bg-[#E50914] rounded-full transition-all duration-1000"
                              style={{ width: `${Math.min((elapsedSec / (eta || 30)) * 100, 95)}%` }}
                            />
                          </div>
                        </div>
                        <div className="space-y-3 text-left">
                          {steps.map((step, i) => (
                            <div key={i} className="flex items-center gap-3">
                              <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                                step.status === "done" ? "bg-[#46D369]" :
                                step.status === "active" ? "bg-[#E50914] dot-pulse" :
                                step.status === "error" ? "bg-[#E50914]" :
                                "bg-[#333]"
                              }`} />
                              <span className={`text-sm ${
                                step.status === "done" ? "text-[#46D369]" :
                                step.status === "active" ? "text-white" :
                                step.status === "error" ? "text-[#E50914]" :
                                "text-[#555]"
                              }`}>
                                {step.label}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Expired — aguardando reenvio */}
                    {jobStatus === "expired_waiting" && (
                      <div className="mb-4">
                        <div className="w-16 h-16 rounded-full bg-[#F5A623]/20 flex items-center justify-center mx-auto mb-5">
                          <svg className="w-8 h-8 text-[#F5A623]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        </div>
                        <h2 className="text-xl font-bold text-[#F5A623] mb-2">Link Expirado!</h2>
                        <p className="text-white text-sm mb-5">
                          Encontramos o email, mas o link/código já está <strong>expirado</strong> (mais de 15 min).
                          <br /><br />
                          <span className="text-[#F5A623] font-semibold">Reenvie a solicitação</span> no serviço e clique em <strong>"Sim, reenviei"</strong> quando o novo email chegar.
                        </p>

                        <p className="text-[#888] text-sm mb-5 bg-[#1a1a1a] rounded p-3 border border-[#333]">
                          ⏳ Aguardando confirmação... A tela permanece aqui, você não precisa logar de novo.
                        </p>

                        <button
                          onClick={handleReenvio}
                          className="w-full py-4 rounded font-bold text-[15px] tracking-wide bg-[#46D369] hover:bg-[#3aba5a] text-black transition-all mb-3"
                        >
                          ✅ SIM, REENVIEI — BUSCAR NOVO
                        </button>

                        <button
                          onClick={reset}
                          className="w-full py-3 rounded font-semibold text-sm bg-[#222] hover:bg-[#333] text-[#888] transition-colors"
                        >
                          NÃO, FECHAR
                        </button>
                      </div>
                    )}

                    {/* Found */}
                    {jobStatus === "found" && (
                      <div className="mb-4">
                        <>
                          {/* Normal found */}
                          <div className="w-16 h-16 rounded-full bg-[#46D369]/20 flex items-center justify-center mx-auto mb-5">
                            <svg className="w-8 h-8 text-[#46D369]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                            </svg>
                          </div>
                          <h2 className="text-2xl font-bold text-white mb-2">Link Encontrado!</h2>
                          <p className="text-[#8c8c8c] text-sm mb-6">Clique no botão abaixo para acessar.</p>
                        </>

                        {extractedLink && (
                          <a
                            href={extractedLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block w-full py-4 rounded font-bold text-[15px] tracking-wide text-white text-center transition-all bg-[#E50914] hover:bg-[#F40612] pulse-red"
                          >
                            ACESSAR LINK
                          </a>
                        )}

                        {extractedCode && (
                          <div className="mt-5 p-5 bg-[#161616] rounded border border-[#333]">
                            <p className="text-[#8c8c8c] text-xs mb-2">Seu código:</p>
                            <p className="text-3xl font-bold tracking-[0.3em] font-mono text-white">
                              {extractedCode}
                            </p>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Not found — aguardando reenvio */}
                    {(jobStatus === "not_found" || jobStatus === "not_found_waiting") && (
                      <div className="mb-4">
                        <div className="w-16 h-16 rounded-full bg-[#F5A623]/20 flex items-center justify-center mx-auto mb-5">
                          <svg className="w-8 h-8 text-[#F5A623]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        </div>
                        <h2 className="text-xl font-bold text-white mb-2">Email Não Encontrado</h2>
                        <p className="text-white text-sm mb-5">
                          Nenhum email foi encontrado nos últimos 15 minutos.
                          <br /><br />
                          <span className="text-[#F5A623] font-semibold">Reenvie a solicitação</span> no serviço e clique em <strong>"Sim, reenviei"</strong> quando o novo email chegar.
                        </p>

                        <p className="text-[#888] text-sm mb-5 bg-[#1a1a1a] rounded p-3 border border-[#333]">
                          ⏳ Aguardando confirmação... A tela permanece aqui, você não precisa logar de novo.
                        </p>

                        <div className="bg-[#1a1212] rounded p-3 text-left mb-5 border border-[#E50914]/20">
                          <p className="text-[#E50914] text-xs font-semibold mb-1">⚠️ Você selecionou a opção correta?</p>
                          <p className="text-[#666] text-xs">
                            Opção selecionada: <strong className="text-white">{selectedServiceData?.title}</strong>
                          </p>
                        </div>

                        <button
                          onClick={handleReenvio}
                          className="w-full py-4 rounded font-bold text-[15px] tracking-wide bg-[#46D369] hover:bg-[#3aba5a] text-black transition-all mb-3"
                        >
                          ✅ SIM, REENVIEI — BUSCAR NOVO
                        </button>

                        <button
                          onClick={reset}
                          className="w-full py-3 rounded font-semibold text-sm bg-[#222] hover:bg-[#333] text-[#888] transition-colors"
                        >
                          NÃO, FECHAR
                        </button>
                      </div>
                    )}

                    {/* Error */}
                    {jobStatus === "error" && (
                      <div className="mb-4">
                        <div className="w-16 h-16 rounded-full bg-[#E50914]/20 flex items-center justify-center mx-auto mb-5">
                          <svg className="w-8 h-8 text-[#E50914]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </div>
                        <h2 className="text-xl font-bold text-white mb-2">Erro ao Acessar</h2>
                        <p className="text-[#8c8c8c] text-sm mb-4">
                          {errorMessage || "Erro ao acessar o email."}
                        </p>
                        <div className="bg-[#161616] rounded p-4 text-left mb-4 border border-[#333]">
                          <p className="text-[#E50914] text-sm font-semibold mb-2">Possíveis causas:</p>
                          <ul className="text-[#B3B3B3] text-sm space-y-1.5">
                            <li>• Email ou senha incorretos</li>
                            <li>• Conta com verificação em duas etapas</li>
                            <li>• Conta bloqueada temporariamente</li>
                          </ul>
                          <p className="text-[#666] text-xs mt-3">
                            Se o erro persistir, entre em contato com o suporte.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Back button */}
                    {(jobStatus === "found" || jobStatus === "error") && (
                      <button
                        onClick={reset}
                        className="w-full py-3 rounded font-semibold text-sm bg-[#222] hover:bg-[#333] text-white transition-colors mt-2"
                      >
                        VOLTAR AO INÍCIO
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Footer */}
            <div className="text-center mt-8 space-y-1">
              <p className="text-[#444] text-xs">
                Serviço automatizado • Links expiram após uso
              </p>
              <p className="text-[#555] text-[10px] uppercase tracking-widest">
                Serviço criado exclusivamente por LKLOGINS LTDA
              </p>
            </div>
          </div>
        </main>
      </div>

      {/* Confirmation Popup */}
      {showConfirm && selectedServiceData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setShowConfirm(false)} />
          <div className="relative bg-[#141414] rounded-lg border border-[#333] p-6 md:p-8 max-w-[420px] w-full shadow-2xl">
            {/* Warning icon */}
            <div className="w-14 h-14 rounded-full bg-[#F5A623]/20 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-[#F5A623]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M12 2L2 22h20L12 2z" />
              </svg>
            </div>

            <h3 className="text-xl font-bold text-white text-center mb-3">
              {selectedServiceData.confirmTitle}
            </h3>

            <p className="text-white text-center text-[15px] font-medium mb-3">
              {selectedServiceData.confirmMessage}
            </p>

            <p className="text-[#8c8c8c] text-sm text-center mb-4">
              {selectedServiceData.confirmDetail}
            </p>

            {selectedServiceData.confirmLink && (
              <a
                href={selectedServiceData.confirmLink}
                target="_blank"
                rel="noopener noreferrer"
                className="block w-full py-3 rounded font-semibold text-sm bg-[#222] hover:bg-[#333] text-[#E50914] text-center transition-colors mb-3 border border-[#333]"
              >
                {selectedServiceData.confirmLinkText}
              </a>
            )}

            <button
              onClick={startExtraction}
              className="w-full py-3.5 rounded font-bold text-[14px] tracking-wide bg-[#E50914] hover:bg-[#F40612] text-white transition-all mt-1"
            >
              {selectedServiceData.confirmButton}
            </button>

            <button
              onClick={() => setShowConfirm(false)}
              className="w-full py-2.5 rounded font-medium text-sm text-[#666] hover:text-[#999] transition-colors mt-2"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}


    </div>
  );
}
