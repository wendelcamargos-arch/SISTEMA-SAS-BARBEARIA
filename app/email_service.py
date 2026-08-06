"""E-mail transacional — provider abstrato com implementação simulada e SMTP.

Usado pela recuperação de senha (link white label por tenant). O token puro
NUNCA é registrado em log; apenas seu hash vai ao banco (app/auth.py).
Configuração SMTP por ambiente: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
SMTP_FROM, SMTP_STARTTLS. Sem SMTP_HOST, opera o provider simulado.
"""
import os
import smtplib
from abc import ABC, abstractmethod
from email.mime.text import MIMEText


class EmailProvider(ABC):
    @abstractmethod
    def enviar(self, destinatario: str, assunto: str, corpo_html: str) -> bool: ...


class SimuladoEmailProvider(EmailProvider):
    """Desenvolvimento/teste: guarda em memória, nada sai para a rede."""

    def __init__(self):
        self.enviados: list[dict] = []

    def enviar(self, destinatario: str, assunto: str, corpo_html: str) -> bool:
        self.enviados.append({"para": destinatario, "assunto": assunto, "corpo": corpo_html})
        return True


class SMTPProvider(EmailProvider):
    def __init__(self):
        self.host = os.environ["SMTP_HOST"]
        self.porta = int(os.environ.get("SMTP_PORT", "587"))
        self.usuario = os.environ.get("SMTP_USER", "")
        self.senha = os.environ.get("SMTP_PASSWORD", "")
        self.remetente = os.environ.get("SMTP_FROM", self.usuario)
        self.starttls = os.environ.get("SMTP_STARTTLS", "1") == "1"

    def enviar(self, destinatario: str, assunto: str, corpo_html: str) -> bool:
        msg = MIMEText(corpo_html, "html", "utf-8")
        msg["Subject"] = assunto
        msg["From"] = self.remetente
        msg["To"] = destinatario
        try:
            with smtplib.SMTP(self.host, self.porta, timeout=15) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.usuario:
                    smtp.login(self.usuario, self.senha)
                smtp.sendmail(self.remetente, [destinatario], msg.as_string())
            return True
        except Exception:
            # sem detalhes no log para não vazar configuração; auditoria registra a falha
            return False


_provider: EmailProvider | None = None


def obter_email_provider() -> EmailProvider:
    global _provider
    if _provider is None:
        _provider = SMTPProvider() if os.environ.get("SMTP_HOST") else SimuladoEmailProvider()
    return _provider


def definir_email_provider(p: EmailProvider | None) -> None:
    """Injeção para testes."""
    global _provider
    _provider = p


def corpo_recuperacao(nome_barbearia: str, nome_usuario: str, link: str) -> tuple[str, str]:
    """Assunto e corpo white label por tenant."""
    assunto = f"{nome_barbearia} — redefinição de senha"
    corpo = f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2>{nome_barbearia}</h2>
      <p>Olá, {nome_usuario.split()[0]}. Recebemos um pedido para redefinir sua senha.</p>
      <p><a href="{link}" style="background:#C9A227;color:#141414;padding:12px 22px;
         border-radius:8px;text-decoration:none;font-weight:bold">Redefinir senha</a></p>
      <p style="color:#777;font-size:13px">O link vale por 1 hora e só pode ser usado uma vez.
      Se você não pediu a redefinição, ignore este e-mail.</p>
    </div>"""
    return assunto, corpo
