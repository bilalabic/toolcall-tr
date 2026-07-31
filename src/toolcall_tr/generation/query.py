"""Türkçe kullanıcı ifadesi üretimi.

Çevrimdışı korpusun temeli elle yazılmış Türkçe ifadelerdir
(`Blueprint.utterances`). OpenAI modunda LLM blueprint'ten özgün soru ve kısa,
denetlenebilir karar gerekçesi üretir; kaynak ifade doğal dil çıpası olarak kalır.

İki üretici aynı arayüzü uygular:

`TemplateQueryGenerator`
    Deterministik, API anahtarı istemez, CI'da çalışır. Elle yazılmış
    ifadeleri seçer ve hafif stil dönüşümleri uygular.
`LLMQueryGenerator`
    Gerçek model ile soru ve kısa gerekçe üretir. Ürettiği metin yine
    **doğrulanır**: argüman değerleri metinde geçmiyorsa grounding
    validator reddeder -- LLM'e güvenilmez, kontrol edilir.

Her iki durumda da LLM **ground-truth üretmez**; yalnızca doğal dil yazar.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from toolcall_tr.canonical import sha256_of
from toolcall_tr.llm.base import LLMClient, LLMMessage, LLMResponse
from toolcall_tr.llm.cache import LLMCache
from toolcall_tr.models import Blueprint, LLMUsage
from toolcall_tr.seeds import episode_rng
from toolcall_tr.turkish import ascii_fold_tr

__all__ = [
    "PROMPT_VERSION",
    "STYLES",
    "TEMPLATE_FRAMES",
    "GeneratedQuery",
    "LLMQueryGenerator",
    "QueryGenerator",
    "TemplateCapacityExceededError",
    "TemplateQueryGenerator",
]

#: Provenance'a yazılır. Prompt değişince artırılır ve önbellek geçersizleşir.
PROMPT_VERSION = "toolcall-tr-user-v6"

#: `configs/generation.yaml` ile aynı liste.
STYLES: tuple[str, ...] = (
    "resmi",
    "gunluk",
    "eksiltili",
    "yazim_hatali",
    "dolayli",
    "uzun_baglam",
    "karisik_dil",
)

#: Ağ veya LLM gerektirmeyen canary üretiminde kullanılan, anlamı değiştirmeyen
#: Türkçe söylem çerçeveleri. ``{query}`` içindeki elle incelenmiş ifade olduğu
#: gibi korunur; dolayısıyla sayılar, tarihler, açık onay ifadeleri ve diğer
#: ground-truth değerleri kaybolmaz.
TEMPLATE_FRAMES: tuple[tuple[str, str], ...] = (
    ("ham", "{query}"),
    ("rica", "Rica etsem, {query}"),
    ("kontrol", "Şunu kontrol edebilir misin: {query}"),
    ("bilgi_ihtiyaci", "Şu bilgiye ihtiyacım var: {query}"),
    ("kisa_yanit", "Mümkünse kısaca yanıtla: {query}"),
    ("not_icin", "Notlarıma eklemek için soruyorum: {query}"),
    ("tek_konu", "Yalnızca şu konuda yardım istiyorum: {query}"),
    ("netlestirme", "Şu noktayı netleştirelim: {query}"),
    ("teyit", "Şu bilgiyi teyit etmek istiyorum: {query}"),
    ("uygunsa", "Uygunsa buna bakar mısın: {query}"),
    ("oncelikli", "Öncelikle şu soruya yanıt arıyorum: {query}"),
    ("dogrudan", "Doğrudan sonucu paylaşabilir misin: {query}"),
    ("planlama", "Planımı buna göre yapacağım; {query}"),
    ("yardim", "Bu konuda yardımcı olur musun? {query}"),
    ("ozet", "Özet bir yanıt yeterli: {query}"),
    ("benim_icin", "Benim için şu bilgiyi bulur musun: {query}"),
    ("merak", "Şu ayrıntıyı merak ettim: {query}"),
    ("destek", "Şu konuda desteğe ihtiyacım var: {query}"),
    ("kontrol_listesi", "Kontrol listemde şu kaldı: {query}"),
    ("gereken_bilgi", "Gereken bilgi şu: {query}"),
    ("soyle_sorayim", "Şöyle sorayım: {query}"),
    ("acik_yanit", "Yanıtı açık biçimde yazar mısın: {query}"),
    ("vakit", "Vaktin olduğunda şunu kontrol et: {query}"),
    ("son_bir_soru", "Son bir sorum var: {query}"),
    ("karar_oncesi", "Karar vermeden önce bunu bilmeliyim: {query}"),
    ("yalin", "Yalın bir yanıtla şunu açıklar mısın: {query}"),
    ("ayrinti", "İhtiyacım olan ayrıntı şu: {query}"),
    ("bakabilir_misin", "Şuna bakabilir misin? {query}"),
    ("sonuc", "Sonucu benimle paylaş: {query}"),
    ("kisa_bir_soru", "Kısa bir soru: {query}"),
    ("bilgi_notu", "Bir bilgi notu hazırlıyorum; {query}"),
    ("tamamlamak_icin", "Çalışmamı tamamlamak için şunu bilmeliyim: {query}"),
)


class NoUtteranceError(ValueError):
    """Blueprint'te hiç doğal dil ifadesi yok."""


class TemplateCapacityExceededError(ValueError):
    """Şablon üreticisinin benzersiz varyant kapasitesi aşıldı."""


@dataclass(frozen=True, slots=True)
class GeneratedQuery:
    """Üretilmiş tek bir kullanıcı ifadesi."""

    text: str
    style: str
    variant_index: int
    prompt_version: str
    reasoning_summary_tr: str | None = None
    usage: LLMUsage | None = None


class QueryGenerator(Protocol):
    prompt_version: str

    def generate(
        self,
        blueprint: Blueprint,
        *,
        variant_index: int,
        root_seed: int,
        repair_feedback: Sequence[str] = (),
    ) -> GeneratedQuery: ...


class TemplateQueryGenerator:
    """Sınırlı kapasiteli deterministik smoke üreticisi.

    Elle yazılmış ifadeleri deterministik Türkçe söylem çerçeveleriyle birleştirir.
    Aynı ``(blueprint_id, variant_index)`` daima aynı metni verir. Çerçeveler,
    ifadeyi içeride değiştirmediği için ground-truth değerleri ve açık onay
    sözcükleri korunur. Kapasite dolunca başa dönmez; aynı soruyu yeni bir
    varyantmış gibi üretmek yerine açıkça hata verir.
    """

    prompt_version = PROMPT_VERSION

    def __init__(self, *, cycle_utterances: bool = True) -> None:
        """Üreticiyi yapılandır.

        ``cycle_utterances=False`` ölçekli canary için kullanılır: her
        blueprint'in pilotta çalıştırılıp doğrulanmış ilk ifadesi korunur,
        çeşitlilik yalnız denetlenmiş söylem çerçevelerinden gelir. İkinci
        ifadeler insan çeşitliliği için değerlidir ancak bazılarında açık bir
        limit gibi ground-truth ayrıntıları doğal olarak eksik bırakılmıştır.
        """
        self.cycle_utterances = cycle_utterances

    def generate(
        self,
        blueprint: Blueprint,
        *,
        variant_index: int = 0,
        root_seed: int = 0,
        repair_feedback: Sequence[str] = (),
    ) -> GeneratedQuery:
        if not blueprint.utterances:
            raise NoUtteranceError(
                f"{blueprint.blueprint_id}: `utterances` boş. Şablon üretici elle "
                "yazılmış ifadelere dayanır."
            )

        if variant_index < 0:
            raise ValueError("variant_index negatif olamaz")
        capacity = self.capacity(blueprint)
        if variant_index >= capacity:
            raise TemplateCapacityExceededError(
                f"{blueprint.blueprint_id}: şablon kapasitesi {capacity}; "
                f"variant_index={variant_index} yeni ve benzersiz bir soru üretemez"
            )

        # Seed bu üreticide metin seçimini etkilemez; parametre arayüz
        # uyumluluğu ve ileride çerçeve sırası değiştirilmeden yapılabilecek
        # kontrollü örnekleme için korunur.
        episode_rng(root_seed, blueprint.blueprint_id, variant_index)
        utterance_count = len(blueprint.utterances) if self.cycle_utterances else 1
        base_index = variant_index % utterance_count
        frame_index = variant_index // utterance_count
        style, frame = TEMPLATE_FRAMES[frame_index]
        text = frame.format(query=blueprint.utterances[base_index])

        return GeneratedQuery(
            text=text,
            style=style,
            variant_index=variant_index,
            prompt_version=self.prompt_version,
            usage=None,
        )

    def capacity(self, blueprint: Blueprint) -> int:
        """Bu blueprint için üretilebilecek en fazla benzersiz şablon sayısı."""
        utterance_count = len(blueprint.utterances) if self.cycle_utterances else 1
        return utterance_count * len(TEMPLATE_FRAMES)


def _apply_style(text: str, style: str) -> str:
    """Hafif, **anlamı bozmayan** stil dönüşümleri.

    Argüman değerleri korunur: grounding validator onları metinde arar.
    Bu yüzden dönüşümler yalnızca çerçeveye dokunur, sayılara ve adlara
    değil -- tek istisna `yazim_hatali`, ki o da Türkçe karakterleri ASCII'ye
    indirger ve bu **gerçek bir kullanıcı davranışıdır**.
    """
    if style == "gunluk":
        return text.replace(" misiniz", " misin").replace(" musunuz", " musun")
    if style == "yazim_hatali":
        # Kullanıcılar Türkçe karakter kullanmadan yazar; Solr bunu farklı
        # sonuçlandırır (q=otobüs -> 17, q=otobus -> 9).
        return ascii_fold_tr(text)
    if style == "eksiltili":
        return text.rstrip("?. ").removesuffix(" acaba")
    if style == "dolayli":
        return f"Merak ediyorum, {text[0].lower()}{text[1:]}"
    if style == "uzun_baglam":
        return f"Bir sunum için veri topluyorum. {text}"
    return text


class LLMQueryGenerator:
    """Gerçek modelle blueprint tabanlı soru ve kısa karar gerekçesi üretir.

    Ürettiği metin doğrulamayı **atlamaz**: argüman değerleri metinde
    geçmiyorsa grounding validator örneği reddeder.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        client: LLMClient,
        *,
        system_prompt: str,
        cache: LLMCache | None = None,
        temperature: float = 1.0,
        max_tokens: int = 512,
        structured_output: bool = True,
        cycle_utterances: bool = False,
        question_mode: Literal["paraphrase", "synthesize"] = "synthesize",
    ) -> None:
        self.client = client
        self.system_prompt = system_prompt
        #: Yeniden çalıştırmayı bedava yapar. Prompt sürümü artınca doğal
        #: olarak geçersizleşir.
        self.cache = cache
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.structured_output = structured_output
        self.cycle_utterances = cycle_utterances
        self.question_mode = question_mode

    def generate(
        self,
        blueprint: Blueprint,
        *,
        variant_index: int = 0,
        root_seed: int = 0,
        repair_feedback: Sequence[str] = (),
    ) -> GeneratedQuery:
        if not blueprint.utterances:
            raise NoUtteranceError(
                f"{blueprint.blueprint_id}: doğal dil referansı için kaynak ifade yok"
            )

        rng = episode_rng(root_seed, blueprint.blueprint_id, variant_index)
        candidate_styles = (
            STYLES
            if "Türkçe karakter kullanmadan" in blueprint.user_goal
            else tuple(style_name for style_name in STYLES if style_name != "yazim_hatali")
        )
        style = "resmi" if variant_index == 0 else rng.choice(candidate_styles)
        utterance_count = len(blueprint.utterances) if self.cycle_utterances else 1
        source = blueprint.utterances[variant_index % utterance_count]

        cache_key: str | None = None
        if self.cache is not None:
            feedback_hash = sha256_of(tuple(repair_feedback))
            cache_key = self.cache.key(
                prompt_version=self.prompt_version,
                blueprint_id=(
                    f"{blueprint.blueprint_id}:{blueprint.content_hash()}:"
                    f"{self.question_mode}:{feedback_hash}"
                ),
                variant_index=variant_index,
                provider=self.client.provider,
                model=self.client.model,
            )
            cached = self.cache.get(cache_key)
            if cached is not None:
                return _to_query(cached, style, variant_index, self.prompt_version)

        messages = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(
                role="user",
                content=_build_prompt(
                    blueprint,
                    source,
                    style,
                    question_mode=self.question_mode,
                    repair_feedback=repair_feedback,
                ),
            ),
        ]
        response = self._complete(messages)
        if self.cache is not None and cache_key is not None:
            self.cache.put(cache_key, response)

        return _to_query(
            response,
            style,
            variant_index,
            self.prompt_version,
            temperature=self.temperature,
        )

    def _complete(self, messages: list[LLMMessage]) -> LLMResponse:
        complete_json = getattr(self.client, "complete_json", None)
        if self.structured_output and callable(complete_json):
            response: LLMResponse = complete_json(
                messages,
                schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                        "reasoning_summary_tr": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 800,
                        },
                    },
                    "required": ["query", "reasoning_summary_tr"],
                    "additionalProperties": False,
                },
                schema_name="toolcall_tr_user_query_v6",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return response
        return self.client.complete(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


def _to_query(
    response: LLMResponse,
    style: str,
    variant_index: int,
    prompt_version: str,
    *,
    temperature: float = 1.0,
) -> GeneratedQuery:
    text = response.text.strip()
    reasoning_summary_tr: str | None = None
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("query"), str):
        text = payload["query"].strip()
        summary = payload.get("reasoning_summary_tr")
        if isinstance(summary, str) and summary.strip():
            reasoning_summary_tr = summary.strip()

    return GeneratedQuery(
        text=text,
        style=style,
        variant_index=variant_index,
        prompt_version=prompt_version,
        reasoning_summary_tr=reasoning_summary_tr,
        usage=LLMUsage(
            provider=response.provider,
            model=response.model,
            prompt_version=prompt_version,
            temperature=temperature,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_input_tokens=response.cached_input_tokens,
            cached=response.cached,
        ),
    )


def _build_prompt(
    blueprint: Blueprint,
    source: str,
    style: str,
    *,
    question_mode: Literal["paraphrase", "synthesize"],
    repair_feedback: Sequence[str] = (),
) -> str:
    """Blueprint kısıtlarından doğal soru ve kısa karar gerekçesi üret.

    Korunması gereken değerler açıkça listelenir; böylece soru özgünleşirken
    deterministik ground-truth ile bağı kopmaz.
    """
    preserved = _preserved_values(blueprint)
    task = (
        "Kaynak cümleyi anlamını koruyarak yeniden yaz."
        if question_mode == "paraphrase"
        else "Blueprint'teki amacı karşılayan yeni ve doğal bir kullanıcı sorusu yaz."
    )
    lines = [
        f"Görev modu: {question_mode}. {task}",
        f"Üslup: {style}",
        "",
        f"Kullanıcı amacı: {blueprint.user_goal}",
        f"Beklenen karar: {blueprint.expected_behavior.decision.value}",
        f"Senaryo türü: {blueprint.kind.value}",
        f"Etkileşim türü: {blueprint.interaction_type}",
        "Önceki konuşma bağlamı: "
        + (
            " | ".join(
                f"{turn.role}: {turn.content}"
                for turn in blueprint.conversation_prefix
            )
            or "(yok)"
        ),
        f"Kaynak cümle (yalnız doğal dil referansı): {source}",
        f"Bilerek eksik bilgiler: {list(blueprint.missing_information)}",
        f"Beklenen cevap niyeti: {blueprint.expected_behavior.response_intent_tr}",
        f"Notlar: {blueprint.notes}",
        "",
        "Query içinde birebir korunacak değerler:",
    ]
    lines.extend(f"  - {value}" for value in preserved)
    lines.append("")
    lines.extend(_behavior_requirements(blueprint))
    if repair_feedback:
        lines.extend(
            [
                "",
                "Önceki aday aşağıdaki kalite nedenleriyle reddedildi:",
                *[f"  - {item[:500]}" for item in repair_feedback[:8]],
                "Yeni adayı yazarken bu nedenleri düzelt; blueprint'in amacını "
                "ve sabit değerlerini değiştirme.",
            ]
        )
    lines.extend(
        [
            "- Query içinde tool adı veya teknik terim kullanma.",
            "- Query'ye yeni amaç, yeni bilgi veya ek görev ekleme.",
            "- multi_turn ise yalnız önceki konuşmayı izleyen son kullanıcı turunu "
            "yaz; konuşma geçmişini query içinde tekrar etme.",
            "- Bu üretim sürümünde veritabanı/tablo/veri seti kataloğu "
            "arama-sorgulama veya sipariş/fatura/ön muhasebe isteği üretme.",
            "- Gerçek kişisel veri üretme.",
            "- reasoning_summary_tr içinde yalnız karar ve kanıt özetini ver; "
            "adım adım iç düşünce yazma.",
        ]
    )
    return "\n".join(lines)


def _preserved_values(blueprint: Blueprint) -> Sequence[str]:
    values = [str(value) for value in blueprint.known_information.values()]
    values.extend(
        str(argument.value)
        for action in blueprint.expected_actions
        for argument in action.arguments.values()
        if argument.kind == "literal"
        and argument.origin.value == "user_message"
        and not isinstance(argument.value, bool)
    )
    values = list(dict.fromkeys(values))
    return values or ["(korunması gereken sabit değer yok)"]


def _behavior_requirements(blueprint: Blueprint) -> list[str]:
    requirements = ["Davranış kuralları:"]
    has_explicit_confirmation = any(
        argument.kind == "literal"
        and argument.origin.value == "user_message"
        and argument.value is True
        for action in blueprint.expected_actions
        for argument in action.arguments.values()
    )
    if has_explicit_confirmation:
        requirements.append(
            "- Kullanıcının işlemi açıkça onayladığını query içinde mutlaka belirt."
        )
    elif (
        blueprint.kind.value == "confirmation_required"
        and blueprint.expected_behavior.decision.value != "tool_call"
    ):
        requirements.append(
            "- Kullanıcı işlem istesin fakat açık onay vermesin; asistanın onay istemesi gerekiyor."
        )
    if "Türkçe karakter kullanmadan" in blueprint.user_goal:
        requirements.append(
            "- Query'nin tamamında yalnız ASCII karakter kullan; ç, ğ, ı, İ, ö, ş, ü kullanma."
        )
    if blueprint.expected_behavior.missing_parameters:
        requirements.append(
            "- Şu eksik bilgileri query'ye ekleme: "
            + ", ".join(blueprint.expected_behavior.missing_parameters)
        )
    return requirements
