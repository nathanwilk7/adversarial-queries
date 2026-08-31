SELECT count(*)
FROM aka_name, company_type, info_type, kind_type, link_type, movie_companies, movie_info, movie_link, name, person_info, title
WHERE aka_name.name = 'Mike'
  AND aka_name.person_id = name.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
