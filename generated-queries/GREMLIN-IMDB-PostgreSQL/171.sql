SELECT count(*)
FROM cast_info, char_name, company_name, info_type, movie_companies, movie_info_idx, person_info, title
WHERE char_name.surname_pcode = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.info_type_id = info_type.id
  AND movie_info_idx.movie_id = title.id
  AND person_info.info_type_id = info_type.id;
