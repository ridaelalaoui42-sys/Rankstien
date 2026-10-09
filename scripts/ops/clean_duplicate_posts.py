import os
import urllib.request

GENIAL_DUPLICATES = [
    # (Keeper ID, Keeper Slug, Duplicate ID, Duplicate Slug)
    (
        "220ec54e-afec-439b-abd8-9ef0da166520",
        "pollo-al-horno-tiempo-y-temperatura-perfectos",
        "49f55239-efbb-427b-b6e9-536cdbd7009d",
        "pollo-al-horno-tiempo-temperatura-perfectos",
    ),
    (
        "4958c2b4-a87d-4a73-b098-369be30fcde7",
        "salmon-al-horno-con-miel-y-mostaza",
        "536e2a99-53cf-4cb3-85d3-ed3b76eccb0e",
        "salmon-horno-miel-mostaza",
    ),
    (
        "cc306a66-afd1-475f-a789-f90ee6ca61a6",
        "tarta-de-queso-cremosa-en-air-fryer",
        "f0ac068d-2a7d-4857-ba58-e0c2b0d6a628",
        "tarta-de-queso-cremosa-air-fryer",
    ),
    (
        "6f8357fe-ef4f-4291-8814-3193e3e7043c",
        "pollo-al-horno-con-patatas-y-cebolla",
        "ec76e415-9e61-48ea-b899-1c50ca1a51a9",
        "pollo-horno-patatas-cebolla",
    ),
    (
        "499aaba0-d9bc-4640-bc82-3ae77cee2997",
        "croquetas-caseras-freidora-aire-crujientes-ligeras",
        "42ad6299-f217-4abd-8dfb-0f6c696e209b",
        "croquetas-caseras-en-freidora-de-aire-crujientes-y-ligeras",
    ),
    (
        "52ec6b77-4d36-41ed-8dfe-80215f5d9d7c",
        "paella-mixta-de-marisco-y-pollo",
        "5c772543-92c2-475d-8d01-c3b91f97ea1a",
        "paella-mixta-marisco-pollo",
    ),
    (
        "51681c49-3975-493d-82a7-76d128cf7157",
        "pescado-frito-crujiente-al-estilo-espanol",
        "69ca3397-3191-49b3-8a4c-5ef881ef2d1a",
        "pescado-frito-crujiente-estilo-espanol",
    ),
    (
        "73c11fea-aaec-407f-9a2f-8c330288627b",
        "pescado-frito-crujiente-al-estilo-casero",
        "ba8e13cb-f5d2-47df-abfa-cad6784b3870",
        "pescado-frito-crujiente-estilo-casero",
    ),
    (
        "7fdcc781-2323-43f3-9c2e-3cf47e7c3146",
        "pescado-frito-crujiente-al-estilo-tradicional",
        "04e199ab-0483-4f1e-916c-9c3836881832",
        "pescado-frito-crujiente-tradicional",
    ),
    (
        "474cb60d-c9bf-44fe-a8bb-1fc5e07b7dee",
        "salmon-al-horno-con-verduras-la-receta-mas-facil-y-saludable",
        "9e55954b-fc87-43ef-b4f6-81a5bb8a91de",
        "salmon-al-horno-verduras-receta-facil-saludable",
    ),
    (
        "474cb60d-c9bf-44fe-a8bb-1fc5e07b7dee",
        "salmon-al-horno-con-verduras-la-receta-mas-facil-y-saludable",
        "8d385e64-a7fb-4ba5-892a-91626f6d5229",
        "salmon-al-horno-con-verduras-receta-facil-saludable",
    ),
    (
        "0b1a393f-2c8d-48d1-b832-ce175836321a",
        "pollo-horno-con-patatas",
        "fb8cbc55-30a7-4858-a703-b067236fc041",
        "pollo-al-horno-con-patatas",
    ),
    (
        "e72084df-500d-462f-b4f0-13fd7bdced70",
        "ensalada-quinoa-kale-aguacate",
        "f4f49601-4347-46f9-b825-f3ce1838c7a5",
        "ensalada-de-quinoa-kale-y-aguacate",
    ),
    (
        "703c82d8-e042-43e7-9867-20f03ebeb09e",
        "pollo-al-horno-con-papas",
        "7a0c2e07-c7bb-43d1-b863-ea1562648201",
        "pollo-horno-con-papas",
    ),
    (
        "36a8cb79-890c-4376-a241-79b93f9cc0b9",
        "croquetas-caseras-de-jamon-iberico-en-freidora-de-aire",
        "8ebaf7a7-f98c-4513-a5f8-10ef498185de",
        "croquetas-caseras-jamon-iberico-freidora-aire",
    ),
    (
        "51d858e8-5096-4c4a-957b-b1a7591e7c21",
        "pescado-frito-crujiente-y-saboroso",
        "12d03418-7e5a-4cf2-9fc2-0721eaeaa85a",
        "pescado-frito-crujiente-saboroso",
    ),
    (
        "1cdb1ce8-6817-4779-9926-e5791a8e5cd4",
        "ensalada-garbanzos-aguacate",
        "3fffbb5a-1fc3-4d7f-b3f3-75fdc4e3aba5",
        "ensalada-de-garbanzos-y-aguacate",
    ),
    (
        "df91d5e7-d2cf-44e0-b6fd-3f83b3df6a10",
        "tarta-de-queso-al-horno-cremosa-y-facil",
        "958bacdf-6fbe-4d19-a498-23a75ad04824",
        "tarta-de-queso-al-horno-cremosa",
    ),
    (
        "73982ff1-3cbf-4e2e-b8be-12caf159e710",
        "tarta-tres-chocolates-mercadona",
        "7bf985d3-b87d-4375-b98d-6cba036b07b8",
        "tarta-tres-chocolates-de-mercadona",
    ),
    (
        "f06493dd-16e2-46b2-8c23-3873e81a0ea3",
        "milanesa-napolitana-al-horno",
        "a767ce1a-35c7-4398-99bf-1abe71bf4761",
        "milanesa-napolitana-al-horno-jugosa-crujiente",
    ),
]

DOLCE_DUPLICATES = [
    # (Keeper ID, Keeper Slug, Duplicate ID, Duplicate Slug)
    (
        "3c8e3564-6d31-41f3-8ed5-1f3ee1413bb7",
        "bizcocho-de-chocolate-para-hombre",
        "ca6ecf9d-3f4a-40eb-843d-bbec7a9af6ed",
        "bizcocho-chocolate-para-hombre",
    ),
    (
        "60dd7e47-766c-4ba7-917d-b6ef1c1586fd",
        "bizcocho-de-chocolate-con-dulce-de-leche",
        "8348a069-dfd0-44b0-9c7a-d19fb0d08455",
        "bizcocho-chocolate-dulce-leche",
    ),
    (
        "adb71294-030b-453c-a8aa-80632172bef0",
        "tarta-de-queso-cremosa-en-freidora-de-aire",
        "9bcaa3bc-3e73-488a-aae7-66e53fae9732",
        "tarta-queso-cremosa-freidora-aire",
    ),
    (
        "afa0f9a3-80ef-4e4d-bae2-68973945c38c",
        "galletas-de-avena-y-platano-saludables",
        "44d63cf7-8332-4692-ad17-8afae7498687",
        "galletas-avena-platano-saludables",
    ),
    (
        "217c94b4-d201-404e-a790-6a355dcce541",
        "tarta-de-queso-en-freidora-de-aire",
        "9d184d89-22fb-4f8a-8b87-34e12b889e16",
        "tarta-de-queso-freidora-aire",
    ),
    (
        "0c09ce3a-a4f9-4537-b3d2-8dc7389e084c",
        "galletas-de-avena-con-chispas-de-chocolate",
        "91603fc9-e9dd-458e-8d39-f0304922acd9",
        "galletas-avena-chispas-chocolate",
    ),
    (
        "8822736c-34cb-484d-a60d-47eb7caee214",
        "bizcocho-de-chocolate-blanco-esponjoso",
        "22e42100-70ee-4605-99ba-a90d7a8e2832",
        "bizcocho-chocolate-blanco-esponjoso",
    ),
    (
        "20044ac5-ba11-4f72-b648-a3a7768a904c",
        "bizcocho-de-chocolate-esponjoso-con-yogur",
        "24cff01b-9a24-4137-abcc-2b795b3f84f5",
        "bizcocho-chocolate-esponjoso-yogur",
    ),
    (
        "177752c2-bd7c-40f2-ac9e-7c50b93814ba",
        "tarta-opera-clasica-francesa-receta-paso-a-paso",
        "4ce677db-b203-4e08-9078-20503668a139",
        "tarta-opera-clasica-francesa",
    ),
    (
        "26d0826f-5e60-4825-a03c-9902495a9a68",
        "macarons-de-lavanda-y-miel-receta-perfecta",
        "437b6771-0725-4228-b3ce-26dab0857f68",
        "macarons-de-lavanda-y-miel",
    ),
]


def delete_duplicates(domain_name, url, key, duplicates_list):
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    print(f"\n=== Deleting {len(duplicates_list)} duplicates from {domain_name} ===")
    deleted_count = 0
    redirects = []

    for keeper_id, keeper_slug, dup_id, dup_slug in duplicates_list:
        redirects.append((f"/{dup_slug}", f"/{keeper_slug}"))
        del_req = urllib.request.Request(
            f"{url}/rest/v1/posts?id=eq.{dup_id}", headers=headers, method="DELETE"
        )
        try:
            with urllib.request.urlopen(del_req):
                print(f" [+] DELETED: {dup_slug} (ID: {dup_id}) -> Keeper: {keeper_slug}")
                deleted_count += 1
        except Exception as e:
            print(f" [!] Error deleting {dup_id}: {e}")

    print(f"Total deleted in {domain_name}: {deleted_count}")
    return redirects


# Execute deletions
genial_reds = delete_duplicates(
    "recetagenial",
    "https://hokcljsrrnjxzgdhjice.supabase.co",
    "os.getenv('RECETAGENIAL_SUPABASE_KEY', '')",
    GENIAL_DUPLICATES,
)
dolce_reds = delete_duplicates(
    "recetadolce",
    "https://xjvmnmfczvwkjiasirsl.supabase.co",
    "os.getenv('RECETADOLCE_SUPABASE_KEY', '')",
    DOLCE_DUPLICATES,
)

print("\nRedirects to add:")
print(f"RecetaGenial: {len(genial_reds)} redirects")
print(f"RecetaDolce: {len(dolce_reds)} redirects")
