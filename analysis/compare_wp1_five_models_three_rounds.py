"""Five-model, three-round WP1 comparison with explicit missingness controls."""
from __future__ import annotations
import csv,json,statistics
from datetime import datetime,timezone
from analysis.analyze_campaign import holm_adjust,paired_comparison
from analysis.compare_wp1_models import PLAN_PATH,RESULTS,mean_ci,rows_for,sha256

ANALYSIS_ID="wp1-five-model-three-round-20260829-v1"
OUTPUT=RESULTS/"round_comparison"/ANALYSIS_ID
ROUNDS=("R001","R002","R003")
MODELS={
 "xAI Grok Build 0.1":{"R001":["EXP-XAI-BUILD01-PILOT-002","EXP-XAI-BUILD01-VARIANTS-REMAINING-001"],"R002":["EXP-R002-XAI-GROK-BUILD01-FULL-001"],"R003":["EXP-R003-XAI-GROK-BUILD01-FULL-001"]},
 "NVIDIA Nemotron 3 Super":{"R001":["EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-INCIDENT01-VARIANTS-002","EXP-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-VARIANTS-REMAINING-001"],"R002":["EXP-R002-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"],"R003":["EXP-R003-OPENROUTER-NVIDIA-NEMOTRON3-SUPER-FULL-001"]},
 "DeepSeek V4 Flash 0731":{"R001":["EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-INCIDENT01-VARIANTS-001","EXP-OPENROUTER-DEEPSEEK-V4-FLASH-0731-VARIANTS-REMAINING-001"],"R002":["EXP-R002-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"],"R003":["EXP-R003-OPENROUTER-DEEPSEEK-V4-FLASH-0731-FULL-001"]},
 "GPT-5.6 Luna":{"R001":["EXP-R001-OPENROUTER-OPENAI-GPT56-LUNA-FULL-001"],"R002":["EXP-R002-OPENROUTER-OPENAI-GPT56-LUNA-FULL-001"],"R003":["EXP-R003-OPENROUTER-OPENAI-GPT56-LUNA-FULL-001"]},
 "Gemini 3.7 Flash":{"R001":["EXP-R001-OPENROUTER-GOOGLE-GEMINI37-FLASH-FULL-001"],"R002":["EXP-R002-OPENROUTER-GOOGLE-GEMINI37-FLASH-FULL-001"],"R003":["EXP-R003-OPENROUTER-GOOGLE-GEMINI37-FLASH-FULL-001"]},
}
def cell_key(r): return r["incident_id"],r["profile"],r["variant"]
def corr(a,b):
 ma,mb=statistics.fmean(a),statistics.fmean(b); den=(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))**.5
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/den if den else 0.0
def icc(vectors):
 n,k=len(vectors[0]),len(vectors); cm=[statistics.fmean(v[j] for v in vectors) for j in range(n)]; rm=[statistics.fmean(v) for v in vectors]; grand=statistics.fmean(cm)
 msc=k*sum((x-grand)**2 for x in cm)/(n-1); mse=sum((vectors[r][j]-cm[j]-rm[r]+grand)**2 for j in range(n) for r in range(k))/((n-1)*(k-1)); return (msc-mse)/(msc+(k-1)*mse) if msc+(k-1)*mse else 0.0
def fmt(x,d=3): return "NA" if x is None else f"{x:.{d}f}"

def main():
 if OUTPUT.exists(): raise FileExistsError(f"immutable output exists: {OUTPUT}")
 plan=json.loads(PLAN_PATH.read_text()); metrics=[plan["primary_metric"],*plan["secondary_metrics"]]; loaded={}; provenance=[]
 for model,rounds in MODELS.items():
  for rid,cids in rounds.items():
   rows,prov=rows_for(model,cids); mapping={cell_key(r):r for r in rows}
   if len(mapping)!=len(rows): raise ValueError(f"duplicate cells: {model} {rid}")
   loaded[model,rid]=mapping; provenance.extend({"model":model,"round":rid,**p} for p in prov)
 universe=set().union(*(set(m) for m in loaded.values()));
 if len(universe)!=192: raise ValueError(f"expected 192-cell universe, got {len(universe)}")
 missing=[]; descriptive=[]; stability=[]
 for model in MODELS:
  for rid in ROUNDS:
   mapping=loaded[model,rid]; missing.append({"model":model,"round":rid,"planned":192,"scored":len(mapping),"missing":192-len(mapping),"completion_rate":len(mapping)/192})
   for metric in metrics:
    vals=[float(r[metric]) for r in mapping.values() if r.get(metric) is not None]; rec={"model":model,"round":rid,"metric":metric}; rec.update(mean_ci(vals,plan,f"five:{model}:{rid}:{metric}")); descriptive.append(rec)
  common=set.intersection(*(set(loaded[model,r]) for r in ROUNDS)); vectors={r:[float(loaded[model,r][k]["overall_score"]) for k in sorted(common)] for r in ROUNDS}; pairs=(("R001","R002"),("R001","R003"),("R002","R003"))
  stability.append({"model":model,"matched_cells":len(common),"icc_3_1":icc([vectors[r] for r in ROUNDS]),"correlations":{f"{a}_{b}":corr(vectors[a],vectors[b]) for a,b in pairs},"rounds":{r:{"scored":len(loaded[model,r]),"overall_score":statistics.fmean(float(x["overall_score"]) for x in loaded[model,r].values()),"actions_per_cell":statistics.fmean(float(x["requested_actions"]) for x in loaded[model,r].values()),"exact_injection_cells":sum(x["injected_actions_requested"]>0 for x in loaded[model,r].values() if x["variant"]!="BASE"),"attacked_cells":sum(x["variant"]!="BASE" for x in loaded[model,r].values()),"policy_integrity_failures":sum(float(x["policy_enforcement_integrity"])<1 for x in loaded[model,r].values())} for r in ROUNDS}})
 # Pair models using incident-level means pooled over all available matched rounds/cells.
 comparisons=[]; model_names=list(MODELS)
 for metric in metrics:
  family=[]
  for i,ref in enumerate(model_names):
   for cmp_model in model_names[i+1:]:
    ref_clusters={}; cmp_clusters={}
    for incident in sorted({k[0] for k in universe}):
     pairs=[]
     for rid in ROUNDS:
      common=set(loaded[ref,rid])&set(loaded[cmp_model,rid])
      for k in common:
       if k[0]==incident and loaded[ref,rid][k].get(metric) is not None and loaded[cmp_model,rid][k].get(metric) is not None: pairs.append((float(loaded[ref,rid][k][metric]),float(loaded[cmp_model,rid][k][metric])))
     if pairs: ref_clusters[("incident",incident,1)]=statistics.fmean(x for x,_ in pairs); cmp_clusters[("incident",incident,1)]=statistics.fmean(y for _,y in pairs)
    rec={"metric":metric,"reference_model":ref,"comparison_model":cmp_model,"unit":"incident_cluster_pooled_rounds"}; rec.update(paired_comparison(ref_clusters,cmp_clusters,plan,f"five-model:{metric}:{ref}:{cmp_model}")); family.append(rec)
  holm_adjust(family); comparisons.extend(family)
 all_common=set.intersection(*(set(loaded[m,r]) for m in MODELS for r in ROUNDS)); matched={m:{r:statistics.fmean(float(loaded[m,r][k]["overall_score"]) for k in all_common) for r in ROUNDS} for m in MODELS}
 result={"schema_version":"1.0","analysis_id":ANALYSIS_ID,"generated_at":datetime.now(timezone.utc).isoformat(),"analysis_plan_hash":sha256(PLAN_PATH),"design":{"models":5,"rounds":3,"planned_cells":2880,"scored_cells":sum(x["scored"] for x in missing),"missing_cells":sum(x["missing"] for x in missing),"cell_universe":192,"all_model_round_complete_case_cells":len(all_common),"independent_incident_clusters":12},"provenance":provenance,"missingness":missing,"descriptive":descriptive,"stability":stability,"all_model_round_matched_overall":matched,"cross_model_comparisons":comparisons,"limitations":["GPT and Gemini retain terminal missing cells; no score imputation was used.","Cross-model inference uses 12 incident clusters; cell-level observations are correlated.","Model identity remains confounded with provider, adapter, and hosted backend.","Retries are provenance, not independent experimental rounds.","NVIDIA routing limitations documented in the earlier three-model analysis remain.","Semantic equivalence labels cover declared variants and may not capture every behavioral analogue.","Non-significance is not evidence of equivalence."]}
 OUTPUT.mkdir(parents=True); (OUTPUT/"five_model_three_round.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
 with (OUTPUT/"cross_model_comparisons.csv").open("w",newline="") as h: w=csv.DictWriter(h,fieldnames=list(comparisons[0])); w.writeheader(); w.writerows(comparisons)
 with (OUTPUT/"missingness.csv").open("w",newline="") as h: w=csv.DictWriter(h,fieldnames=list(missing[0])); w.writeheader(); w.writerows(missing)
 lines=["# WP1 five-model, three-round analysis","",f"Analysis ID: `{ANALYSIS_ID}`","",f"Planned cells: 2,880; scored: {result['design']['scored_cells']}; missing: {result['design']['missing_cells']}. No imputation was used.","","## Overall score and reproducibility","","| Model | R001 | R002 | R003 | Three-round matched n | ICC(3,1) | Exact injection requests R001/R002/R003 | Policy integrity failures |","|---|---:|---:|---:|---:|---:|---:|---:|"]
 for s in stability:
  rr=s["rounds"]; lines.append(f"| {s['model']} | {rr['R001']['overall_score']:.3f} | {rr['R002']['overall_score']:.3f} | {rr['R003']['overall_score']:.3f} | {s['matched_cells']} | {s['icc_3_1']:.3f} | {rr['R001']['exact_injection_cells']}/{rr['R002']['exact_injection_cells']}/{rr['R003']['exact_injection_cells']} | {sum(rr[r]['policy_integrity_failures'] for r in ROUNDS)} |")
 lines += ["","## Missingness","","| Model | R001 | R002 | R003 |","|---|---:|---:|---:|"]
 for m in MODELS: lines.append("| "+m+" | "+" | ".join(str(next(x["missing"] for x in missing if x["model"]==m and x["round"]==r)) for r in ROUNDS)+" |")
 lines += ["","## All-model complete-case overall means","",f"The strict intersection contains {len(all_common)} cells present in every model and every round.","","| Model | R001 | R002 | R003 |","|---|---:|---:|---:|"]
 for m in MODELS: lines.append(f"| {m} | {matched[m]['R001']:.3f} | {matched[m]['R002']:.3f} | {matched[m]['R003']:.3f} |")
 lines += ["","## Interpretation constraints",""]+[f"- {x}" for x in result["limitations"]]
 (OUTPUT/"report.md").write_text("\n".join(lines)+"\n"); print(f"WROTE {OUTPUT}")
if __name__=="__main__": main()
