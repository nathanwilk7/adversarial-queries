SELECT count(*)
FROM company_name, info_type, kind_type, movie_companies, movie_info, movie_link, name, person_info, title
WHERE name.surname_pcode = ''
  AND title.series_years = '1965-1975'
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
