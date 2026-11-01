"""Generates taxonomy.json (default risk taxonomy). Edit here or via Admin UI overrides."""
import json
S = {"critical": 4, "high": 3, "medium": 2, "low": 1}
cats = []
def c(id, group, label, severity, en, other=None, q=None, weight=1.0):
    cats.append({"id": id, "group": group, "label": label, "severity": severity, "weight": weight,
                 "enabled": True, "patterns": {"en": en, **(other or {})}, "query_terms": q or en[:3]})
FC, RG, PR, CI = "financial_crime", "regulatory", "predicate", "integrity"
c("money_laundering", FC, "Money laundering", "critical",
  ["money launder*", "laundering money", "laundered*", "launders", "proceeds of crime", "laundering scheme", "anti-money laundering offence", "money mule*"],
  {"fr": ["blanchiment*"], "de": ["geldwasche*", "geldwaesche*"], "es": ["lavado de dinero", "blanqueo*"], "it": ["riciclaggio*"], "pt": ["lavagem de dinheiro", "branqueamento*"], "nl": ["witwas*"], "ar": ["غسل الأموال", "غسيل الأموال"]},
  ["money laundering", "laundering"])
c("terrorist_financing", FC, "Terrorist financing", "critical",
  ["terrorist financing", "terror financing", "financing terrorism", "financing of terrorism", "terrorism financing", "funding terrorism", "terror funding"],
  {"fr": ["financement du terrorisme"], "de": ["terrorismusfinanzierung"], "es": ["financiacion del terrorismo", "financiamiento del terrorismo"], "it": ["finanziamento del terrorismo"], "pt": ["financiamento do terrorismo"], "nl": ["terrorismefinanciering"], "ar": ["تمويل الإرهاب"]},
  ["terrorist financing"])
c("fraud", FC, "Fraud and financial deception", "high",
  ["fraud", "frauds", "fraudster*", "fraudulent*", "defraud*", "swindl*", "scam", "scammed", "scammer*", "deception", "false representation", "obtaining by deception", "bank fraud", "wire fraud", "mail fraud", "loan fraud", "bounce back loan*"],
  {"fr": ["fraude*", "escroquer*", "escroc*"], "de": ["betrug*", "betrueger*", "betruger*"], "es": ["fraude*", "estafa*"], "it": ["frode*", "truffa*"], "pt": ["fraude*", "golpe"], "nl": ["fraude*", "oplichting"], "ar": ["احتيال"]},
  ["fraud", "fraudulent"])
c("tax_evasion", FC, "Tax evasion and tax fraud", "high",
  ["tax evasion", "evading tax*", "evaded tax*", "tax fraud", "vat fraud", "carousel fraud", "cheating the public revenue", "tax dodg*", "undeclared income"],
  {"fr": ["fraude fiscale", "evasion fiscale"], "de": ["steuerhinterziehung", "steuerbetrug"], "es": ["evasion fiscal", "fraude fiscal"], "it": ["evasione fiscale", "frode fiscale"], "pt": ["evasao fiscal", "sonegacao*"], "nl": ["belastingfraude", "belastingontduiking"], "ar": ["التهرب الضريبي"]},
  ["tax evasion", "tax fraud"])
c("bribery_corruption", FC, "Bribery and corruption", "critical",
  ["brib*", "corrupt*", "kickback*", "graft", "fcpa", "bribery act", "facilitation payment*", "influence peddling"],
  {"fr": ["corruption", "pot-de-vin", "pots-de-vin"], "de": ["bestechung*", "korruption*", "schmiergeld*"], "es": ["soborno*", "corrupcion", "cohecho"], "it": ["corruzione", "tangent*"], "pt": ["suborno*", "corrupcao", "propina*"], "nl": ["omkoping*", "corruptie"], "ar": ["رشوة", "فساد"]},
  ["bribery", "corruption"])
c("embezzlement", FC, "Embezzlement and misappropriation", "high",
  ["embezzl*", "misappropriat*", "siphon*", "theft of funds", "stole from", "breach of trust"],
  {"fr": ["detournement de fonds", "abus de biens sociaux"], "de": ["veruntreu*", "unterschlag*"], "es": ["malversacion", "apropiacion indebida"], "it": ["appropriazione indebita", "peculato"], "pt": ["desvio de fundos", "peculato"], "nl": ["verduistering"], "ar": ["اختلاس"]},
  ["embezzlement", "misappropriation"])
c("insider_trading", FC, "Insider trading / insider dealing", "high",
  ["insider trading", "insider dealing", "trading on inside information", "inside information"],
  {"fr": ["delit d'initie*"], "de": ["insiderhandel"], "es": ["uso de informacion privilegiada"], "it": ["insider trading"], "nl": ["handel met voorkennis"]},
  ["insider trading", "insider dealing"])
c("market_manipulation", FC, "Market manipulation", "high",
  ["market manipulation", "manipulating the market", "manipulated the market", "pump and dump", "pump-and-dump", "spoofing", "price manipulation", "market abuse", "rate rigging", "libor rigging"],
  {"fr": ["manipulation de cours", "manipulation du marche"], "de": ["marktmanipulation"], "es": ["manipulacion del mercado"], "it": ["manipolazione del mercato", "aggiotaggio"], "nl": ["marktmanipulatie"]},
  ["market manipulation", "market abuse"])
c("securities_fraud", FC, "Securities and investment fraud", "high",
  ["securities fraud", "investment fraud", "investor fraud", "defrauding investors", "defrauded investors", "boiler room", "unregistered securities", "misled investors"],
  {"de": ["anlagebetrug"], "fr": ["fraude boursiere"]}, ["securities fraud", "investment fraud"])
c("accounting_fraud", FC, "Accounting fraud", "high",
  ["accounting fraud", "accounting irregularit*", "cooked the books", "false accounting", "accounting scandal", "missing billion*", "balance sheet hole", "fictitious revenue*", "inflated revenue*"],
  {"de": ["bilanzbetrug", "bilanzfalschung", "bilanzfaelschung"], "fr": ["fraude comptable"], "es": ["fraude contable"], "it": ["falso in bilancio"]},
  ["accounting fraud", "false accounting"])
c("financial_statement_manipulation", FC, "Financial statement manipulation", "high",
  ["financial statement fraud", "misstated financial*", "restatement of accounts", "falsified accounts", "falsified financial*", "manipulated accounts", "inflated profits", "window dressing"],
  {}, ["falsified accounts", "misstated financial statements"])
c("ponzi_scheme", FC, "Ponzi schemes and investment scams", "critical",
  ["ponzi", "pyramid scheme", "investment scam*", "investment scheme fraud", "crypto scam*", "rug pull"],
  {"fr": ["systeme de ponzi", "pyramide de ponzi"], "de": ["schneeballsystem"], "es": ["esquema ponzi", "estafa piramidal"], "it": ["schema ponzi"], "pt": ["esquema de piramide", "piramide financeira"], "nl": ["piramidespel"]},
  ["Ponzi scheme", "investment scam"])
c("cyber_financial_crime", FC, "Cyber-enabled financial crime", "high",
  ["ransomware", "phishing", "business email compromise", "account takeover", "card fraud", "crypto theft", "cyber fraud", "cyber-enabled fraud", "hacking scheme", "identity theft"],
  {}, ["cyber fraud", "ransomware"])
c("asset_concealment", FC, "Asset concealment and illicit funds", "high",
  ["illicit funds", "hidden assets", "concealed assets", "concealing assets", "shell compan*", "offshore accounts", "asset freezing order", "unexplained wealth order", "account freezing order", "confiscation order", "dirty money"],
  {"fr": ["avoirs illicites"], "de": ["illegale gelder"], "es": ["fondos ilicitos"]}, ["unexplained wealth order", "illicit funds"])
c("organised_financial_crime", FC, "Organised financial crime", "critical",
  ["fraud ring", "crime network", "criminal network", "money laundering network", "laundering network", "racketeering", "rico"],
  {}, ["racketeering", "criminal network"])
# regulatory
c("regulatory_investigation", RG, "Regulatory investigation", "medium",
  ["under investigation", "investigated by", "investigation into", "probe into", "probed by", "regulator investigat*", "inquiry into", "dawn raid", "raided"],
  {"fr": ["enquete", "perquisition"], "de": ["ermittlung*", "durchsuchung*"], "es": ["investigacion", "pesquisa"], "it": ["indagin*", "inchiesta"], "pt": ["investigacao"], "nl": ["onderzoek naar"], "ar": ["تحقيق"]},
  ["investigation", "probe"])
c("enforcement_action", RG, "Regulatory enforcement action", "high",
  ["enforcement action", "final notice", "cease and desist", "censure*", "public censure", "sanctioned by the", "consent order", "deferred prosecution agreement", "enforcement notice"],
  {"de": ["bafin"], "fr": ["sanction de l'amf", "commission des sanctions"]}, ["enforcement action", "final notice"])
c("fines_penalties", RG, "Financial penalties and fines", "medium",
  ["fined", "fine of", "penalty of", "civil penalty", "monetary penalty", "financial penalty", "ordered to pay", "disgorge*"],
  {"fr": ["amende", "condamne a payer"], "de": ["geldstrafe", "bussgeld"], "es": ["multa", "multado"], "it": ["multa", "sanzione"], "pt": ["multa"], "nl": ["boete"], "ar": ["غرامة"]},
  ["fined", "penalty"])
c("aml_control_failures", RG, "AML/CTF control deficiencies", "high",
  ["aml failings", "anti-money laundering failings", "aml failures", "money laundering controls", "aml controls", "financial crime controls", "weak controls", "failed to prevent money laundering", "know your customer failings", "kyc failings", "suspicious activity reports"],
  {}, ["AML failings", "money laundering controls"])
c("financial_services_breach", RG, "Breach of financial services regulation", "medium",
  ["breach of fca rules", "breached fca", "principles for businesses", "unauthorised firm", "unauthorised investment", "breach of regulations", "regulatory breach*", "failed to comply with regulatory", "breached regulatory", "mifid breach"],
  {}, ["regulatory breach"])
c("licence_revocation", RG, "Licence suspension or revocation", "high",
  ["licence revoked", "license revoked", "revoked its licence", "revoked its license", "licence suspended", "license suspended", "permission cancelled", "authorisation cancelled", "authorization revoked", "stripped of its licence", "banking licence withdrawn"],
  {"de": ["lizenz entzogen"], "fr": ["retrait d'agrement", "licence retiree"]}, ["licence revoked"])
c("professional_disqualification", RG, "Professional disqualification", "high",
  ["disqualified director", "disqualified from acting as a director", "director disqualification", "banned from acting as a director", "struck off", "barred from the industry", "prohibition order", "banned from the financial services industry", "disqualified for"],
  {}, ["disqualified director", "prohibition order"])
c("governance_failings", RG, "Serious governance and control failings", "medium",
  ["governance failings", "control failings", "systems and controls failings", "serious failings", "risk management failings"],
  {}, ["governance failings"])
c("misleading_disclosure", RG, "Misleading disclosures to regulators/investors", "high",
  ["misleading statements", "misled the market", "misled regulators", "false statements to", "misleading the market", "misleading investors", "false and misleading"],
  {}, ["misled investors", "misleading statements"])
c("sanctions_breach", RG, "Sanctions-related breaches and enforcement", "critical",
  ["sanctions breach*", "breach of sanctions", "breaching sanctions", "sanctions evasion", "evading sanctions", "sanctions violation*", "violated sanctions", "ofac penalty", "ofsi penalty", "sanctions busting"],
  {"fr": ["violation des sanctions"], "de": ["sanktionsverstoss*"], "es": ["violacion de sanciones"]}, ["sanctions evasion", "sanctions breach"])
# predicate
c("drug_trafficking", PR, "Drug trafficking", "critical",
  ["drug trafficking", "drug trafficker*", "narcotics trafficking", "drug smuggling", "drug cartel", "cocaine", "heroin trafficking", "fentanyl trafficking", "supplying class a"],
  {"fr": ["trafic de drogue", "trafic de stupefiants"], "de": ["drogenhandel"], "es": ["narcotrafico", "trafico de drogas"], "it": ["traffico di droga", "narcotraffico"], "pt": ["trafico de drogas"], "nl": ["drugshandel"], "ar": ["تهريب المخدرات", "الاتجار بالمخدرات"]},
  ["drug trafficking"])
c("human_trafficking", PR, "Human trafficking", "critical",
  ["human trafficking", "people trafficking", "people smuggling", "sex trafficking", "trafficking of women", "trafficked"],
  {"fr": ["traite des etres humains"], "de": ["menschenhandel"], "es": ["trata de personas"], "it": ["tratta di esseri umani"], "pt": ["trafico de pessoas"], "nl": ["mensenhandel"], "ar": ["الاتجار بالبشر"]},
  ["human trafficking"])
c("modern_slavery", PR, "Modern slavery and forced labour", "critical",
  ["modern slavery", "forced labour", "forced labor", "slave labour", "debt bondage", "child labour", "child labor"],
  {"fr": ["travail force"], "de": ["zwangsarbeit"], "es": ["trabajo forzoso"]}, ["modern slavery", "forced labour"])
c("organised_crime", PR, "Organised crime", "critical",
  ["organised crime", "organized crime", "mafia", "crime boss", "crime family", "gang leader", "cartel", "criminal organisation", "criminal organization"],
  {"fr": ["crime organise"], "de": ["organisierte kriminalitat", "organisierte kriminalitaet"], "es": ["crimen organizado"], "it": ["criminalita organizzata", "camorra", "ndrangheta"], "pt": ["crime organizado"], "nl": ["georganiseerde misdaad"]},
  ["organised crime", "mafia"])
c("smuggling", PR, "Smuggling", "high",
  ["smuggl*", "contraband"], {"fr": ["contrebande"], "de": ["schmuggel*"], "es": ["contrabando"], "it": ["contrabbando"], "pt": ["contrabando"], "nl": ["smokkel*"], "ar": ["تهريب"]}, ["smuggling"])
c("proliferation_financing", PR, "Proliferation financing", "critical",
  ["proliferation financing", "weapons of mass destruction", "nuclear proliferation", "dual-use goods", "arms trafficking", "weapons smuggling", "arms embargo"],
  {}, ["proliferation financing", "arms trafficking"])
c("wildlife_trafficking", PR, "Wildlife trafficking", "high",
  ["wildlife trafficking", "ivory smuggling", "rhino horn", "illegal wildlife trade", "poaching syndicate"],
  {}, ["wildlife trafficking"])
c("environmental_crime", PR, "Environmental crime linked to illicit finance", "high",
  ["illegal logging", "illegal mining", "environmental crime", "waste trafficking", "illegal dumping", "illegal fishing"],
  {}, ["environmental crime", "illegal logging"])
c("serious_commercial_crime", PR, "Serious commercial criminal misconduct", "high",
  ["cartel conduct", "price fixing", "price-fixing", "bid rigging", "bid-rigging", "counterfeit*", "forgery", "forged documents", "extortion", "blackmail"],
  {}, ["price fixing", "extortion"])
# integrity
c("corporate_misconduct", CI, "Serious corporate misconduct", "medium",
  ["corporate misconduct", "wrongdoing", "misconduct", "malpractice", "whistleblower alleg*", "cover-up", "cover up"],
  {}, ["misconduct", "wrongdoing"])
c("governance_scandal", CI, "Material corporate governance scandal", "medium",
  ["governance scandal", "boardroom scandal", "accounting scandal", "scandal-hit", "collapse of"],
  {"de": ["skandal"], "fr": ["scandale"], "es": ["escandalo"], "it": ["scandalo"]}, ["scandal"])
c("misuse_client_funds", CI, "Misuse of client or investor funds", "high",
  ["client money", "client funds", "customer funds", "investor funds", "misused funds", "commingl*", "client assets"],
  {}, ["client funds", "investor funds"])
c("insolvency_misconduct", CI, "Insolvency misconduct", "medium",
  ["wrongful trading", "fraudulent trading", "phoenix compan*", "insolvency fraud", "bankruptcy fraud", "bankruptcy restrictions", "asset stripping"],
  {"de": ["insolvenzverschleppung"]}, ["fraudulent trading", "insolvency fraud"])
c("conflict_of_interest", CI, "Serious conflicts of interest", "medium",
  ["conflict of interest", "conflicts of interest", "self-dealing", "related-party transactions", "nepotism", "cronyism"],
  {}, ["conflict of interest"])
c("compliance_controversy", CI, "Significant controversy with compliance relevance", "low",
  ["whistleblower", "short seller report", "short-seller report", "allegations of impropriety", "audit failure", "auditor resigned", "refused to sign off"],
  {}, ["whistleblower"], weight=0.5)
groups = {FC: "Financial crime", RG: "Regulatory and compliance", PR: "Predicate offences and serious criminality", CI: "Corporate integrity and reputational"}
not_material = {
 "civil_dispute": ["divorce", "custody battle", "defamation", "libel", "employment tribunal", "unfair dismissal", "neighbour dispute", "boundary dispute", "probate dispute", "inheritance row", "contract dispute", "copyright infringement", "patent infringement"],
 "minor_infraction": ["speeding", "parking ticket", "parking fine", "traffic offence", "driving ban", "drink driving", "drink-driving", "littering", "tv licence"],
 "non_financial_context": ["football", "premier league", "match fixing in", "transfer window", "box office", "album", "concert", "recipe", "film review", "fantasy", "video game", "netflix series", "novel", "tv drama", "podcast episode"],
}
json.dump({"version": 1, "groups": groups, "severity_scale": S, "categories": cats, "not_material": not_material},
          open("taxonomy.json", "w"), ensure_ascii=False, indent=1)
print(len(cats), "categories")
