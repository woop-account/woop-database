"""SQL builders for the WOOP Audience Explorer refresh (Metabase database 67, MySQL).
Rules used (agreed so far):
  consented mom = has an opt-in row for a WOOP organisation
  unique mom    = earliest consented lead per UniqueIdentifier (provisional key)
  data points   = number of non-blank answer fields on the lead (no names, emails, phones, addresses)
"""
BQ = ("India_PampersPremiumCare_Features Indo_AbbottPediasure_UsageStaus PH_JJMilkRiceBathLotion_Preference PH_JJMilkRiceBathLotion_BabySkin PH_JJMilkRiceBathLotion_BestSkincareRegimen Agegroup_YoungestChild IND_PET IND_Beauty_Concerns IND_Family_HealthConcerns IND_City IND_PregnancyPackage_Budget IND_Caregiver Ind_Diaper_Size Ind_MoreThan65kDeliveryExpense INDO_OralHealthProblem INDO_Hijab INDO_SocialMedia Monthly_Income Dog_FoodBrand Dog_Size Dog_Age Zwitsal_AloeveraLotion Zwitsal_HairLotion Caregiver DateToJoin_Kulwhap_Webinars VaselineM_BodycareFormat VaselineM_BodycareAdvantages UL_OPTIN_EML UL_OPTIN_SMS PH_Trimester LifeCell_Occupation CreditCard CharityNGO UnderarmIssue DeoRoll Allergy SkinCare UL_CompetitorBrands UL_SnackPreference UL_RecipesSearch UL_CookingFor mom_community addcol1 cat_breed cat_age first_time_pet Sanitary_Pad BirthYear toothpaste gender product_buy product_categeory new_mom body_lotion freq_purchasing money_spent education cat_food pet_concern brand_premium hair_care hair_concern hair_brand deo_brand body_concern deo_format ethnicity dove1 dove2 lifebouy1 lifebuoy2 addcol2 FoodbrandPreference MilkInsights PregnancyInsights MaternalMilkInsights addcol3 LaundryInsights EngagementInsights".split()
      + [f"addcol{i}" for i in range(4, 28)])
CO = ["MomDOB","MomAge","DueDate","ChildDOB","AdditionalChildDOB","SecondChildDOB","ChildGender","OnlinePurchases","OwnedAppliances","PreferredFormulaMilkBrand","PreferredDiapersBrand","PreferredMaternalMilkBrand","MomsInterests","Occupation","PreferredBabySkinCareBrand","BreastpumpInsights","MotherhoodChallangesInsights","HealthConcerns","BrandsYouUse","HouseholdIncome","WOOPSegment","ENFASegment","ChildHeight","ChildWeight","ChildShowcaseSign","AnybodyType2Diabetes","Type2DiabetesSupplements","UrinaryIncontinence","PickyEater"]
DATE_COLS = {"MomDOB", "DueDate", "ChildDOB", "AdditionalChildDOB", "SecondChildDOB"}
ORG = "('WOOP INDIA','WOOP PH','WOOP INDO','WOOP MY','WOOP TH','WOOP Vietnam','WOOP Singapore')"

def ans(t, col):
    """1 if the answer has any visible character (blank, spaces and newline-only answers count as empty)."""
    return f"({t}.{col} IS NOT NULL)" if col in DATE_COLS else f"COALESCE({t}.{col} REGEXP '[^[:space:]]', 0)"

DP = " + ".join([ans("c", x) for x in CO] + [ans("b", x) for x in BQ])
FROM_WHERE = lambda a, b, before: f""" FROM SURVEY_ANYPLACE_LEADS l
 LEFT JOIN SURVEY_ANYPLACE_COMPUTATION c ON c.LeadId = l.id
 LEFT JOIN SURVEY_ANYPLACE_BrandQ b ON b.LeadId = l.id
 WHERE l.id BETWEEN {a} AND {b}{f" AND l.CreatedDate < '{before}'" if before else ""}
  AND EXISTS (SELECT 1 FROM OPT_IN_SA_LEADS o WHERE o.LeadId = l.id AND o.Organisation IN {ORG})"""
CANON = f"(NULLIF(TRIM(l.UniqueIdentifier),'') IS NULL OR NOT EXISTS (SELECT 1 FROM SURVEY_ANYPLACE_LEADS l2 WHERE l2.UniqueIdentifier = l.UniqueIdentifier AND l2.id < l.id AND EXISTS (SELECT 1 FROM OPT_IN_SA_LEADS o2 WHERE o2.LeadId = l2.id AND o2.Organisation IN {ORG})))"
COUNTRY = "CASE WHEN x.Country IN ('India','Indonesia','Malaysia','Philippines') THEN x.Country ELSE 'Other ASEAN' END"

def q1(a, b, before=None):
    """Query 1: totals per country. before='2026-03-01' counts only leads created before that date."""
    return f"""SELECT {COUNTRY} AS country,
 COUNT(*) AS consented_leads, SUM(x.canon) AS unique_moms, SUM(x.dp) AS data_points
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 2 DESC"""

# --- Query 2: macro audiences ---------------------------------------------------------------
NO_CHILD = ("don.t have|do not have|tidak punya anak|tidak mempunyai anak|tidak ada anak|không có con|"
           "\u0e44\u0e21\u0e48\u0e21\u0e35\u0e25\u0e39\u0e01|"                      # Thai: no child
           "\u0b95\u0bc1\u0bb4\u0ba8\u0bcd\u0ba4\u0bc8\u0b95\u0bb3\u0bcd \u0b87\u0bb2\u0bcd\u0bb2\u0bc8|"   # Tamil: no children
           "\u0c2a\u0c3f\u0c32\u0c4d\u0c32\u0c32\u0c41 \u0c32\u0c47\u0c30\u0c41")            # Telugu: no children
DOGCAT = ("dog|cat|anjing|kucing|chó|mèo|"
          "\u0ba8\u0bbe\u0baf\u0bcd|\u0baa\u0bc2\u0ba9\u0bc8|"                      # Tamil: dog, cat
          "\u0c15\u0c41\u0c15\u0c4d\u0c15|\u0c2a\u0c3f\u0c32\u0c4d\u0c32\u0c3f|"        # Telugu: dog, cat
          "\u0e2a\u0e38\u0e19\u0e31\u0e02|\u0e41\u0e21\u0e27")                    # Thai: dog, cat
def q2(a, b, before=None):
    """Query 2: moms and data points per country for Kids, Pets and the 45-plus part of Senior & health.
    Women = all moms (use Query 1). The caregiver part of Senior & health needs a definition from the data team."""
    flags = f"""
  IFNULL(c.ChildDOB >= '1990-01-01' AND c.ChildDOB <= NOW(), 0) AS k_dob,
  IFNULL(c.DueDate >= '2015-01-01', 0) AS k_due,
  IFNULL(b.Agegroup_YoungestChild REGEXP '[^[:space:]]' AND NOT (b.Agegroup_YoungestChild REGEXP '{NO_CHILD}'), 0) AS k_age,
  IFNULL(b.IND_PET REGEXP '{DOGCAT}', 0) AS p_ind,
  ({ans('b','Dog_Age')} + {ans('b','Dog_Size')} + {ans('b','Dog_FoodBrand')} + {ans('b','cat_age')} + {ans('b','cat_breed')} + {ans('b','cat_food')} > 0) AS p_other,
  IFNULL(LOWER(TRIM(b.Caregiver)) IN ('yes','ya','có'), 0) AS cg,
  IFNULL((c.MomDOB > '1940-12-31' AND c.MomDOB <= DATE_SUB(CURDATE(), INTERVAL 45 YEAR)) OR (c.MomAge REGEXP '^(above|diatas|lebih|46|5[0-9])'), 0) AS age45"""
    return f"""SELECT {COUNTRY} AS country,
 SUM(x.canon) AS unique_moms,
 SUM(x.canon * (x.k_dob OR x.k_due OR x.k_age)) AS kids_moms, SUM((x.k_dob OR x.k_due OR x.k_age) * x.dp) AS kids_dp,
 SUM(x.canon * (x.p_ind OR x.p_other)) AS pets_moms, SUM((x.p_ind OR x.p_other) * x.dp) AS pets_dp,
 SUM(x.canon * x.age45) AS seniors_45_plus_moms, SUM(x.age45 * x.dp) AS seniors_45_plus_dp,
 SUM(x.canon * x.k_dob) AS chk_kids_by_child_dob, SUM(x.canon * x.k_age * (1 - x.k_dob) * (1 - x.k_due)) AS chk_kids_by_agegroup_only,
 SUM(x.canon * x.p_ind) AS chk_pets_by_pet_answer, SUM(x.canon * x.cg) AS chk_caregiver_yes, SUM(x.canon * x.age45) AS chk_age_45_plus
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp,{flags}
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 2 DESC"""
